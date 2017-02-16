import sys
# Remove current dir from sys.path, otherwise setuptools will peek up our
# module instead of system's.
sys.path.pop(0)
from setuptools import setup
sys.path.append("..")

setup(name='micropython-uaioftp',
      version='0.9.1',
      description='Lightweight ftp asyncio library for MicroPython.',
      long_description=open('README.md').read(),
      url='https://github.com/cwyark/micropython-uaioftp',
      author='Chester Tseng',
      author_email='cwyark@gmail.com',
      maintainer='Chester',
      maintainer_email='cwyark@gmail.com',
      license='MIT',
      install_requires=['micropython-logging'],
      py_modules=['uaioftp'])
