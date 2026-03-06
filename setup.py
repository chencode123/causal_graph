from setuptools import setup, find_packages

setup(
    name="causal_graphviz",
    version="0.1",
    packages=find_packages(where="utils"),
    package_dir={"": "utils"},
)
