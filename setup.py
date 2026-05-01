"""
Setup script for the Proxmox MCP server.
This file is maintained for compatibility with older tools.
For modern Python packaging, see pyproject.toml.
"""

from setuptools import setup, find_packages

# Metadata and dependencies are primarily managed in pyproject.toml
# This file exists for compatibility with tools that don't support pyproject.toml

setup(
    name="proxmox-mcp-plus",
    version="0.4.5",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.11",
    install_requires=[
        "mcp>=1.8.0,<2.0.0",
        "proxmoxer>=2.0.1,<3.0.0",
        "requests>=2.31.0,<3.0.0",
        "pydantic>=2.0.0,<3.0.0",
        "fastapi>=0.115.0",
        "uvicorn[standard]>=0.30.0",
        "mcpo>=0.0.17",
        "paramiko>=3.0.0,<4.0.0",
        "anyio>=4.0.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0,<8.0.0",
            "black>=24.3.0,<27.0.0",
            "mypy>=1.0.0,<2.0.0",
            "pytest-asyncio>=0.21.0,<0.22.0",
            "ruff>=0.1.0,<0.2.0",
            "build>=1.2.0,<2.0.0",
            "types-paramiko>=4.0.0.20250822,<5.0.0",
            "types-requests>=2.31.0,<3.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "proxmox-mcp=proxmox_mcp.server:main",
            "proxmox-mcp-plus=proxmox_mcp.server:main",
        ],
    },
    author="Kevin",
    author_email="kevin@example.com",
    description="Enhanced Proxmox MCP Server",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    license="MIT",
    keywords=["proxmox", "mcp", "virtualization", "cline", "qemu", "lxc"],
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: System :: Systems Administration",
    ],
    project_urls={
        "Homepage": "https://github.com/RekklesNA/ProxmoxMCP-Plus",
        "Documentation": "https://github.com/RekklesNA/ProxmoxMCP-Plus#readme",
        "Repository": "https://github.com/RekklesNA/ProxmoxMCP-Plus.git",
        "Issues": "https://github.com/RekklesNA/ProxmoxMCP-Plus/issues",
    },
)
