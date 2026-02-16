"""Setup script for archery_parser package."""
from setuptools import setup, find_packages

setup(
    name="archery-parser",
    version="1.0.0",
    description="Ianseo PDF qualification result → structured CSV pipeline",
    author="Vana-Võidu Vibuklubi",
    license="MIT",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.10",
    install_requires=[
        "pdfplumber>=0.10",
        "flask>=3.0",
        "gunicorn>=21.0",
    ],
    entry_points={
        "console_scripts": [
            "archery-parser=archery_parser.cli:main",
        ],
    },
)
