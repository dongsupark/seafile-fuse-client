from setuptools import setup, find_packages

__version__ = '0.0.1'


setup(name='seafile-fuse-client',
      version=__version__,
      license='BSD',
      description='Fuse client based on Python Seafile API',
      author='Dongsu Park',
      author_email='hipporoll@posteo.de',
      url='http://hipporoll.net',
      platforms=['Any'],
      packages=find_packages(),
      install_requires=['requests'],
      classifiers=['Development Status :: 4 - Beta',
                   'License :: OSI Approved :: BSD License',
                   'Operating System :: OS Independent',
                   'Programming Language :: Python'],
      )
