import os # Required for path operations
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioConnectionParams, StdioServerParameters
from google.adk.tools.openapi_tool.auth.auth_helpers import token_to_scheme_credential

TARGET_FOLDER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__))+"\\ai_allowed_folder")
filesystem = MCPToolset(
    connection_params=StdioConnectionParams(
        server_params = StdioServerParameters(
            command='npx',
            args=[
                "-y",  # Argument for npx to auto-confirm install
                "@modelcontextprotocol/server-filesystem",
                TARGET_FOLDER_PATH
            ],
        ),
        timeout=60,
    ),
    # Optional: Filter which tools from the MCP server are exposed
    # tool_filter=['list_directory', 'read_file']
)

fetch = MCPToolset(
    connection_params=StdioConnectionParams(
        server_params = StdioServerParameters(
            command='uvx',
            args=[
                "mcp-server-fetch",
            ],
        ),
        timeout=60,
    ),
)