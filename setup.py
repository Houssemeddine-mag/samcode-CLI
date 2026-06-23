from setuptools import setup, find_packages
from pathlib import Path

this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text(encoding="utf-8") if (this_directory / "README.md").exists() else ""

setup(
    name='samcode-cli',
    version='1.2.0',  # Bumped for refactor
    description='An autonomous AI coding agent that runs in your terminal.',
    long_description=long_description,
    long_description_content_type="text/markdown",
    author='Magra Houssem Eddine',
    packages=find_packages(),  # Automatically finds the 'samcode' package
    install_requires=[
        'rich', 'questionary', 'prompt_toolkit', 'requests', 'beautifulsoup4'
    ],
    entry_points={
        'console_scripts': [
            'samcode=samcode.__main__:main', 
        ],
    },
)