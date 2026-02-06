"""
Setup script for the Proxmox MCP server.
This file is maintained for compatibility with older tools.
For modern Python packaging, see pyproject.toml.
"""

from setuptools import setup, find_packages

# Metadata and dependencies are primarily managed in pyproject.toml
# This file exists for compatibility with tools that don't support pyproject.toml

setup(
    name="proxmox-mcp",
    version="0.1.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.9",
    install_requires=[
        "mcp @ git+https://github.com/modelcontextprotocol/python-sdk.git",
        "proxmoxer>=2.0.1,<3.0.0",
        "requests>=2.31.0,<3.0.0",
        "pydantic>=2.0.0,<3.0.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0,<8.0.0",
            "black>=23.0.0,<24.0.0",
            "mypy>=1.0.0,<2.0.0",
            "pytest-asyncio>=0.21.0,<0.22.0",
            "ruff>=0.1.0,<0.2.0",
            "types-requests>=2.31.0,<3.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "proxmox-mcp=proxmox_mcp.server:main",
        ],
    },
    author="Kevin",
    author_email="kevin@example.com",
    description="A Model Context Protocol server for interacting with Proxmox hypervisors",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    license="MIT",
    keywords=["proxmox", "mcp", "virtualization", "cline", "qemu", "lxc"],
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: System :: Systems Administration",
        "Topic :: System :: Virtualization",
    ],
    project_urls={
        "Homepage": "https://github.com/yourusername/proxmox-mcp",
        "Documentation": "https://github.com/yourusername/proxmox-mcp#readme",
        "Repository": "https://github.com/yourusername/proxmox-mcp.git",
        "Issues": "https://github.com/yourusername/proxmox-mcp/issues",
    },
)
