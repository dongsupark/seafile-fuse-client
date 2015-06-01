#!/usr/bin/env python

"""
  FUSE-based client for Seafile
   - written by Dongsu Park <dpark@posteo.net>
  (inspired by copy-fuse <https://github.com/copy-app/copy-fuse>)

  A simple client for seafile.com, implemented via FUSE.
  This tool allows a Linux/MacOSX client to mount a seafile cloud drive on a
  local filesystem.

  Quickstart usage:

  $ mkdir -p /mnt/seafile
  $ ./seafilefuse.py "http://127.0.0.1:8000" test@seafiletest.com "testtest" /mnt/seafile

  (where server URL is "http://127.0.0.1:8000", username is test@seafiletest.com,
   and password is "testtest".)

  To unmount it:

  $ fusermount -u /mnt/seafile
"""

from errno import ENOENT, EIO
from stat import S_IFDIR, S_IFREG
from sys import argv, exit, stderr

import os
import argparse
import tempfile
import time
import hashlib

from fuse import FUSE, FuseOSError, Operations, LoggingMixIn

from seafileapi.client import SeafileApiClient
from seafileapi.exceptions import ClientHttpError, DoesNotExist
from seafileapi.files import SeafDir, SeafFile
from seafileapi.repo import Repo
from seafileapi.repos import Repos

# global configurable variables to be connected to a Seafile server.
sf_server_url="http://127.0.0.1:8000"
sf_username="test@seafiletest.com"
sf_password="testtest"
sf_mount_point="/mnt/seafile"
repo_id_len=36
cache_ttl=10

def seafile_read_envs():
    global sf_server_url, sf_username, sf_password, sf_mount_point

    if os.environ.get('SEAFILE_TEST_SERVER_ADDRESS') is not None:
        sf_server_url = os.environ['SEAFILE_TEST_SERVER_ADDRESS']
    if os.environ.get('SEAFILE_TEST_USERNAME') is not None:
        sf_username = os.environ['SEAFILE_TEST_USERNAME']
    if os.environ.get('SEAFILE_TEST_PASSWORD') is not None:
        sf_password = os.environ['SEAFILE_TEST_PASSWORD']
    if os.environ.get('SEAFILE_TEST_MOUNT_POINT') is not None:
        sf_mount_point = os.environ['SEAFILE_TEST_MOUNT_POINT']

def seafile_list_repos(client):
    global repo_id_len

    repos = client.repos.list_repos()
    for repo in repos:
        assert len(repo.id) == repo_id_len
    return repos

def seafile_find_repo(repos, repoid=None):
    if repoid is None:
        # just return the first repo if no repo is matched
        return repos[0]

    for tmprepo in repos:
        if tmprepo.id == repoid:
            return tmprepo

    # not found, raise exception
    raise FuseOSError(ENOENT)

class SeafileCache:
    """class for handling caches of file attributes as well as expiration time.
    SeafileCache instances must be initialized by SeafileFUSE.
    """
    def __init__(self, repo):
        self.attrcache = {}
        self.expirecache = {}
        self.currepo = repo

    def __str__(self, msg):
        print 'SeafileCache: %s' % msg

    def list_objects(self, path, ttl=cache_ttl):
        global cache_ttl

        # check expiration time cache
        if path in self.expirecache:
            if self.expirecache[path] >= time.time():
                return self.attrcache[path]

        self.attrcache[path] = {}
        try:
            parentdir = self.currepo.get_dir(path)
            entries = parentdir.ls(force_refresh=True)
        except ClientHttpError as err:
            print "list_objects: err: " + str(err)
            return self.attrcache[path]
        except IOError as err:
            print "list_objects: err: " + str(err)
            return self.attrcache[path]

        for entry in entries:
            #name = os.path.basename(entry.path).encode('utf8')
            name = os.path.basename(entry.path)
            self.add_attrcache(path, name, entry.isdir, entry.size)

        # update expiration time cache
        self.expirecache[path] = time.time() + ttl

        return self.attrcache[path]

    def add_attrcache(self, pdirpath, filename, isdir=False, size=0):
        """adds a new cache entry to self.attrcache, no matter if the entry for
        the path already exists.
        """
        if isdir:
            ftype = 'dir'
        else:
            ftype = 'file'

        self.attrcache[pdirpath][filename] = \
            {'name': filename, 'type': ftype, 'size': size, 'ctime': time.time(), 'mtime': time.time()}

    def update_attrcache(self, pdirpath, filename, isdir=False, size=0):
        """update an existing cache entry in self.attrcache, only if it
        already exists for the path as a key.
        """
        if pdirpath in self.attrcache:
            self.add_attrcache(pdirpath, filename, isdir, size)

class SeafileFUSE(LoggingMixIn, Operations):
    """Main class of the seafile client filesystem based on FUSE.
    On initialization, basic connections are established via SeafileApiClient.
    Only one seafile repository is to be selected for further operations.
    SeafileCache instance must be initialized from the init method as well.
    """
    def __init__(self, server=sf_server_url, username=sf_username, \
            password=sf_password, repoid=None, logfile=None):
        try:
            self.seafileapi_client = SeafileApiClient(server, username, password)
        except ClientHttpError as err:
            print __str__(err)
        except DoesNotExist as err:
            print __str__(err)

        self.logfile = logfile
        self.fobjdict = {}

        self.repos = seafile_list_repos(self.seafileapi_client)
        self.currepo = seafile_find_repo(self.repos, repoid)
        print "Current repo's ID: " + self.currepo.id

        self.seafile_cache = SeafileCache(self.currepo)

    def __str__(self, msg):
        print 'SeafileFUSE: %s' % msg

    def file_close(self, path):
        if path in self.fobjdict:
            if self.fobjdict[path]['modified'] == True:
                self.file_upload(path)
            self.fobjdict[path]['object'].close()
            del self.fobjdict[path]

    def file_get(self, path, download=True):
        # print "file_get: " + path
        if path in self.fobjdict:
            return self.fobjdict[path]

        if download == True:
            sfileobj = self.currepo.get_file(path)
            fcontent = sfileobj.get_content()
        else:
            fcontent = ''

        f = tempfile.NamedTemporaryFile(delete=False)
        f.write(fcontent)
        self.fobjdict[path] = {'object': f, 'modified': False}

        # print "written to tmpfile " + f.name
        # print "fcontent: " + fcontent

        return self.fobjdict[path]

    def file_rename(self, old, new):
        if old in self.fobjdict:
            self.fobjdict[new] = self.fobjdict[old]
            del self.fobjdict[old]

    def file_upload(self, path):
        if path not in self.fobjdict:
            print "file_upload: path(" + path + ") not found in cache"
            raise FuseOSError(EIO)

        fileobj = self.file_get(path)
        if fileobj['modified'] == False:
            # print "not doing upload. return true"
            return True

        fp = fileobj['object']
        fp.seek(0)

        if path == '/':
            pdirpath = '/'
        else:
            pdirpath = os.path.dirname(path)
        targetdir = self.currepo.get_dir(pdirpath)

        nfilename = os.path.basename(path)

        try:
            targetfile = targetdir.upload(fp, nfilename)
        except ClientHttpError as err:
            print __str__("err: " + str(err))
            return 0
        except IOError as err:
            print __str__("err: " + str(err))
            return 0
        except DoesNotExist as err:
            print __str__("err: " + str(err))
            return 0

        # print "uploaded " + nfilename

        fileobj['modified'] = False

    def getattr(self, path, fh=None):
        # print "getattr: " + path
        if path == '/':
            st = dict(st_mode=(S_IFDIR | 0755), st_nlink=2)
            st['st_ctime'] = st['st_atime'] = st['st_mtime'] = time.time()
        else:
            name = str(os.path.basename(path))
            objects = self.seafile_cache.list_objects(os.path.dirname(path))

            if name not in objects:
                raise FuseOSError(ENOENT)
            elif objects[name]['type'] == 'file':
                st = dict(st_mode=(S_IFREG | 0644), st_size=int(objects[name]['size']))
            else:
                st = dict(st_mode=(S_IFDIR | 0755), st_nlink=2)

            st['st_ctime'] = st['st_atime'] = objects[name]['ctime']
            st['st_mtime'] = objects[name]['mtime']

        st['st_uid'] = os.getuid()
        st['st_gid'] = os.getgid()
        return st

    def open(self, path, flags):
        # print "open: " + path
        self.file_get(path)
        return 0

    def flush(self, path, fh):
        # print "flush: " + path
        try:
            if path in self.fobjdict:
                if self.fobjdict[path]['modified'] == True:
                    self.file_upload(path)
        except DoesNotExist as err:
            print __str__("flush: err: " + str(err))

    def fsync(self, path, datasync, fh):
        # print "fsync: " + path
        try:
            if path in self.fobjdict:
                if self.fobjdict[path]['modified'] == True:
                    self.file_upload(path)
        except DoesNotExist as err:
            print __str__("fsync: err: " + str(err))

    def read(self, path, size, offset, fh):
        f = self.file_get(path)['object']
        f.seek(offset)
        return f.read(size)

    def write(self, path, data, offset, fh):
        # print "write: " + path
        fileobj = self.file_get(path)
        f = fileobj['object']
        f.seek(offset)
        f.write(data)
        fileobj['modified'] = True
        return len(data)

    def readdir(self, path, fh):
        # print "readdir: " + path

        objsdict = self.seafile_cache.list_objects(path);
        outlist = ['.', '..']
        for obj in objsdict:
            outlist.append(obj)

        return outlist

    def rename(self, oldname, newname):
        # print "rename: " + oldname + " to " + newname
        self.file_rename(oldname, newname)

        ofilename = os.path.basename(oldname)
        podirname = os.path.dirname(oldname)
        pndirname = os.path.dirname(newname)
        targetfile = self.currepo.get_file(oldname)

        if podirname != pndirname:
            # use moveTo operation for moving it to a different directory
            targetfile.moveTo(pndirname, dst_repo=None)
            tmpname = os.path.join(pndirname, ofilename)
            targetfile = self.currepo.get_file(tmpname)

        # simply call a rename method
        targetfile.rename(newname.strip("/"))

        return 0

    def create(self, path, mode):
        # print "create: " + path

        nfilename = os.path.basename(path)

        pdirpath = os.path.dirname(path)
        parentdir = self.currepo.get_dir(pdirpath)
        parentdir.ls()
        self.seafile_cache.update_attrcache(pdirpath, nfilename, isdir=False)

        self.file_get(path, download=False)
        self.file_upload(path)
        return 0

    def unlink(self, path):
        # print "unlink: " + path
        if path == '/':
            raise FuseOSError(EFAULT)

        targetfile = self.currepo.get_file(path)
        targetfile.delete()

        tfilename = os.path.basename(path)
        pdirpath = os.path.dirname(path)
        self.seafile_cache.update_attrcache(pdirpath, tfilename, isdir=False)

        return 0

    def mkdir(self, path, mode):
        # print "mkdir: " + path
        ndirname = os.path.basename(path)
        pdirpath = os.path.dirname(path)
        parentdir = self.currepo.get_dir(pdirpath)
        parentdir.ls()
        self.seafile_cache.update_attrcache(pdirpath, ndirname, isdir=True)

        newdir = parentdir.mkdir(ndirname)

        return 0

    def rmdir(self, path):
        # print "rmdir: " + path

        if path == '/':
            raise FuseOSError(EFAULT)

        targetdir = self.currepo.get_dir(path)
        targetdir.delete()

        tdirname = os.path.basename(path)
        pdirpath = os.path.dirname(path)
        self.seafile_cache.update_attrcache(pdirpath, tdirname, isdir=True)

        return 0

    def release(self, path, fh):
        # print "release: " + path
        try:
            if self.fobjdict[path]['modified'] == True:
                self.file_close(path)
        except DoesNotExist as err:
            print __str__("release, err: " + str(err))

    def truncate(self, path, length, fh=None):
        # print "truncate: " + path
        f = self.file_get(path)['object']
        f.truncate(length)

    # Disable unused operations:
    access = None
    chmod = None
    chown = None
    getxattr = None
    listxattr = None
    opendir = None
    releasedir = None
    statfs = None

def main():
    parser = argparse.ArgumentParser(
        description='Fuse filesystem for seafile clients')

    parser.add_argument(
        '-d', '--debug', default=False, action='store_true',
        help='turn on debug output (implies -f)')
    parser.add_argument(
        '-f', '--foreground', default=False, action='store_true',
        help='run in foreground')

    repoid = None
    parser.add_argument(
        '-r', '--repoid', type=str,
        help='specify ID of the remote repository (if not set, auto-choose the 1st repo)')

    parser.add_argument(
        '-o', '--options', help='add extra fuse options (see "man fuse")')

    parser.add_argument(
        'server_url', metavar='SERVERURL', help='server_url')
    parser.add_argument(
        'username', metavar='EMAIL', help='username/email')
    parser.add_argument(
        'password', metavar='PASS', help='password')
    parser.add_argument(
        'mount_point', metavar='MNTDIR', help='directory to mount filesystem at')

    args = parser.parse_args(argv[1:])

    seafile_read_envs()

    u_server_url = args.__dict__.pop('server_url')
    if u_server_url is not None:
        sf_server_url = u_server_url
    u_username = args.__dict__.pop('username')
    if u_username is not None:
        sf_username = u_username
    u_password = args.__dict__.pop('password')
    if u_password is not None:
        sf_password = u_password
    u_mount_point = args.__dict__.pop('mount_point')
    if u_mount_point is not None:
        sf_mount_point = u_mount_point

    u_repoid = args.__dict__.pop('repoid')

    # parse options
    options_str = args.__dict__.pop('options')
    options = dict([(kv.split('=', 1)+[True])[:2] for kv in (options_str and options_str.split(',')) or []])

    fuse_args = args.__dict__.copy()
    fuse_args.update(options)

    logfile = None
    if fuse_args.get('debug', False) == True:
        # send to stderr same as where fuse lib sends debug messages
        logfile = stderr

    fuse = FUSE(SeafileFUSE(server=sf_server_url, username=sf_username, \
            password=sf_password, repoid=u_repoid, logfile=logfile), \
            sf_mount_point, **fuse_args)


if __name__ == "__main__":
	main()
