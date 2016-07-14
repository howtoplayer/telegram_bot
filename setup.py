from setuptools import setup, find_packages


requirements = None
with open('requirements.txt') as f:
    requirements = f.readlines()


setup(
    name='erepublikby_bot',
    author='Aliaksiej Homza',
    author_email='aliaksei.homza@gmail.com',
    version='1.0.0',
    packages=find_packages(),
    install_requires=requirements)
