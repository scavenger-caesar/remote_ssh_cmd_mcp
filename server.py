import os
from pydantic import BaseModel, Field
from typing import Literal
from contextlib import asynccontextmanager

from labgrid import Target
from labgrid.resource import NetworkService
from labgrid.driver import SSHDriver

from fastmcp import FastMCP
from fastmcp.server.context import Context
from fastmcp.contrib.mcp_mixin import MCPMixin, mcp_tool

class SshConnectResponse(BaseModel):
    connect_status: Literal["connected", "disconnected"] = Field(..., description="Connection status")
    message: str = Field(..., description="Message about the connection status")

class RunCommandResponse(BaseModel):
    stdout: str = Field(..., description="Standard output")
    stderr: str = Field(..., description="Standard error")
    returncode: int = Field(..., description="Return code")

class CopyFileResponse(BaseModel):
    status: Literal["success", "failed"] = Field(..., description="Copy status")
    message: str = Field(..., description="Message about the copy status")

@asynccontextmanager
async def lifespane(_: FastMCP):
    connections: dict[str, SSHDriver] = {}
    try:
        yield {"connections": connections}
    finally:
        for con, ssh_drv in connections.items():
            try:
                ssh_drv.target.decative(ssh_drv)
            except Exception:
                pass
        connections.clear()

mcp = FastMCP("remote_shell_dev", lifespan=lifespane)

class RemoteShellDevSkills(MCPMixin):
    @mcp_tool(
        name="connect_ssh",
        description="Connect to a remote device via SSH",
        
    )
    async def connect_ssh(
        self,
        address: str,
        username: str,
        password: str,
        port: int = 22,
        ctx: Context = None ,
    )->SshConnectResponse:
        """Connect to a remote device via SSH

        Args:
            address (str): IP address of the remote device
            username (str): Username for the remote device
            password (str): Password for the remote device
            port (int, optional): Port for the remote device. Defaults to 22.
            ctx (Context, optional): Context for the remote device. Defaults to None.
        """
        await ctx.info(f"Connecting to {address}")

        connections: dict = ctx.lifespan_context["connections"]
        if address in connections:
            return SshConnectResponse(
                connect_status="connected",
                message=f"SSH connection to {address} already established"
            )
        
        target = Target(
            name=f"ssh_{address}",
        )   
        network_service = NetworkService(
            target=target,
            address=address,
            username=username,
            password=password,
            port=port,
        )
        ssh_driver = SSHDriver(
            target=target,
        )
        ssh_driver.target = target

        target.activate(ssh_driver)
        connections[address] = ssh_driver
        await ctx.info(f"Connected to {address}")
        
        return SshConnectResponse(
            connect_status="connected",
            message=f"SSH connection to {address} established"
        )

    @mcp_tool(
        name="disconnect_ssh",
        description="Disconnect from a remote device via SSH",
    )
    async def disconnect_ssh(
        self,
        address: str,
        ctx: Context = None,
    )->SshConnectResponse:
        """Disconnect from a remote device via SSH

        Args:
            address (str): IP address of the remote device
            ctx (Context, optional): Context for the remote device. Defaults to None.
        """
        await ctx.info(f"Disconnecting from {address}")

        connections: dict = ctx.lifespan_context["connections"]
        ssh_driver = connections.pop(address, None)
        if ssh_driver is None:
            return SshConnectResponse(
                connect_status="disconnected",
                message=f"SSH connection to {address} not established"
            )
        
        try:
            ssh_driver.target.deactivate(ssh_driver)
        except Exception as e:
            await ctx.warning(f"Error disconnecting from {address}: {e}")
        
        await ctx.info(f"Disconnected from {address}")
        return SshConnectResponse(
            connect_status="disconnected",
            message=f"SSH connection to {address} disconnected"
        )

    @mcp_tool(
        name="run_command",
        description="Run a command on a remote device via SSH",
    )
    async def run_command(
        self,
        address: str,
        command: str,
        timeout: int = 60,
        ctx: Context = None,
    )->RunCommandResponse | SshConnectResponse:
        """Run a command on a remote device via SSH

        Args:
            address (str): IP address of the remote device
            command (str): Command to run
            ctx (Context, optional): Context for the remote device. Defaults to None.
        """
        await ctx.info(f"Running command on {address}: {command}")

        connections: dict = ctx.lifespan_context["connections"]
        ssh_driver: SSHDriver = connections.get(address, None)
        if ssh_driver is None:
            return SshConnectResponse(
                connect_status="disconnected",
                message=f"{address} is not connected, please call connect_ssh first"
            )

        await ctx.info(f"Executing command on {address}: {command}")
        await ctx.report_progress(0, 100, "Executing command")
        
        stdout, stderr, exitcode = ssh_driver.run(command, timeout=timeout)
        await ctx.report_progress(100, 100, "Command executed")
        
        return RunCommandResponse(
            stdout='\n'.join(stdout),
            stderr='\n'.join(stderr),
            returncode=exitcode,
        )

    @mcp_tool(
        name="copy_file_to_remote",
        description="Copy a file to a remote device via SSH",
    )
    async def copy_file_to_remote(
        self,
        address: str,
        local_path: str,
        remote_path: str,
        ctx: Context = None,
    )->CopyFileResponse | SshConnectResponse:
        """Copy a file to a remote device via SSH

        Args:
            address (str): IP address of the remote device
            local_path (str): Local path of the file
            remote_path (str): Remote path of the file
            ctx (Context, optional): Context for the remote device. Defaults to None.
        """
        await ctx.info(f"Copying file to {address}: {local_path} -> {remote_path}")

        connections: dict = ctx.lifespan_context["connections"]
        ssh_driver: SSHDriver = connections.get(address, None)
        if ssh_driver is None:
            return SshConnectResponse(
                connect_status="disconnected",
                message=f"{address} is not connected, please call connect_ssh first"
            )

        await ctx.info(f"Copying file to {address}: {local_path} -> {remote_path}")
        await ctx.report_progress(0, 100, "Copying file")
        
        ret = ssh_driver.scp(src=local_path, dst=f":{remote_path}")
        if ret != 0:
            return CopyFileResponse(
                status="failed",
                message=f"Failed to copy file to {address}: {local_path} -> {remote_path}"
            )

        await ctx.report_progress(100, 100, "File copied")
        
        return CopyFileResponse(
            status="success",
            message=f"File copied to {address}: {local_path} -> {remote_path}"
        )

    @mcp_tool(
        name="copy_file_from_remote",
        description="Copy a file from a remote device via SSH",
    )
    async def copy_file_from_remote(
        self,
        address: str,
        remote_path: str,
        local_path: str,
        ctx: Context = None,
    )->CopyFileResponse | SshConnectResponse:
        """Copy a file from a remote device via SSH

        Args:
            address (str): IP address of the remote device
            remote_path (str): Remote path of the file
            local_path (str): Local path of the file
            ctx (Context, optional): Context for the remote device. Defaults to None.
        """
        await ctx.info(f"Copying file from {address}: {remote_path} -> {local_path}")

        connections: dict = ctx.lifespan_context["connections"]
        ssh_driver: SSHDriver = connections.get(address, None)
        if ssh_driver is None:
            return SshConnectResponse(
                connect_status="disconnected",
                message=f"{address} is not connected, please call connect_ssh first"
            )

        await ctx.info(f"Copying file from {address}: {remote_path} -> {local_path}")
        await ctx.report_progress(0, 100, "Copying file")
        
        ret = ssh_driver.scp(src=f":{remote_path}", dst=local_path)
        if ret != 0:
            return CopyFileResponse(
                status="failed",
                message=f"Failed to copy file from {address}: {remote_path} -> {local_path}"
            )

        await ctx.report_progress(100, 100, "File copied")
        
        return CopyFileResponse(
            status="success",
            message=f"File copied from {address}: {remote_path} -> {local_path}"
        )

skill = RemoteShellDevSkills()
skill.register_tools(mcp)

def main():
    mcp.run()

if __name__ == "__main__":
    main()