"""PyInstaller hook for the MCP SDK without its optional CLI frontend.

Computer Controller uses the SDK/server/client packages, not mcp.cli. Excluding mcp.cli keeps
Typer/Python-dotenv out of the Windows runtime and avoids importing optional CLI code
while PyInstaller discovers submodules.
"""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = collect_submodules(
    "mcp",
    filter=lambda name: not (name == "mcp.cli" or name.startswith("mcp.cli.")),
)
hiddenimports += collect_submodules("mcp_types")
datas = collect_data_files("mcp") + collect_data_files("mcp_types")
