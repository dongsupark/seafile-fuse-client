# Readme for seafile-fuse-client

## Prequisites

Install python-seafile:

	$ git clone https://github.com/dongsupark/python-seafile.git
	$ cd python-seafile
	$ python setup.py install

Install required packages:

(on Debian/Ubuntu/etc.)

	$ sudo apt-get install libfuse2 python-setuptools

(on Fedora/CentOS/SuSE/etc.)

	$ sudo yum install fuse python-setuptools

Set up a seafile server, as introduced in tutorials on <http://manual.seafile.com/>.

## Usage How To

Clone the seafile-fuse-client repo

	# git clone https://github.com/dongsupark/seafile-fuse-client.git
	# cd seafile-fuse-client

ensure that seafilefuse.py is executable

	# sudo chmod +x seafilefuse.py

execute seafilefuse.py

	# ./seafilefuse.py "http://127.0.0.1:8000" user@email.com password /path/to/mount/point

to unmount an existing seafile directory

	# fusermount -u /path/to/mount/point


# Author
 Dongsu Park <dpark@posteo.net>
  - inspired by copy-fuse <https://github.com/copy-app/copy-fuse>
