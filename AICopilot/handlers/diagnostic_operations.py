"""diagnostic_operations.py - Diagnostic and debugging handler for production support."""
import json
import os
import socket
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .base import BaseHandler


class DiagnosticOpsHandler(BaseHandler):
    """Handler for self-diagnostic checks and log export.
    
    Provides production-ready diagnostic tools:
    - run_self_diagnostic: Battery of system checks (socket, FreeCAD, permissions, performance)
    - export_diagnostic_log: Collect logs into exportable package
    """
    
    _ALLOWED_OPERATIONS = frozenset({
        "run_self_diagnostic",
        "export_diagnostic_log",
    })
    
    # Constants
    DISCOVERY_DIR = os.path.expanduser("~/.cache/freecad-mcp/instances")
    DEBUG_LOG_DIR = "/tmp/freecad_mcp_debug"
    OPLOG_PATH = "/tmp/freecad_mcp_oplog.json"
    
    def __init__(self, handler_registry=None, log_operation=None, capture_state=None):
        """Initialize diagnostic handler.
        
        Args:
            handler_registry: Parent MCPHandler instance (for context)
            log_operation: Logging callback
            capture_state: State capture callback
        """
        super().__init__()
        self.handler_registry = handler_registry
        self.log_operation = log_operation
        self.capture_state = capture_state
        self.checks_performed: List[Dict[str, Any]] = []
    
    # ─────────────────────────────────────────────────────────────────
    # run_self_diagnostic: Comprehensive system check
    # ─────────────────────────────────────────────────────────────────
    
    def run_self_diagnostic(self, args: Dict[str, Any]) -> str:
        """Execute a battery of diagnostic checks on the FreeCAD MCP system.
        
        Args:
            include_performance (bool, optional): If True, run performance benchmarks
            include_logs (bool, optional): If True, include recent log snippets
        
        Returns:
            JSON with {"ok": bool, "details": {...}, "message": "..."}
            
        Details structure:
            {
                "checks": [
                    {"name": str, "status": "PASS" | "FAIL" | "WARN", "details": str},
                    ...
                ],
                "summary": {
                    "total": int,
                    "passed": int,
                    "failed": int,
                    "warnings": int
                },
                "system_info": {...}
            }
        """
        try:
            include_performance = args.get("include_performance", False)
            include_logs = args.get("include_logs", False)
            
            checks = []
            
            # 1. FreeCAD Process Check
            checks.append(self._check_freecad_running())
            
            # 2. Socket Connectivity Check
            checks.append(self._check_socket_connectivity())
            
            # 3. Discovery System Check
            checks.append(self._check_discovery_system())
            
            # 4. Debug Log Directory Check
            checks.append(self._check_log_directory())
            
            # 5. Flatpak Permissions Check (Linux)
            if self._is_linux():
                checks.append(self._check_flatpak_permissions())
            
            # 6. Disk Space Check
            checks.append(self._check_disk_space())
            
            # 7. Operation Log Health Check
            checks.append(self._check_operation_log())
            
            # Optional: Performance Benchmarks
            if include_performance:
                checks.append(self._benchmark_socket_latency())
            
            # Summary
            summary = {
                "total": len(checks),
                "passed": sum(1 for c in checks if c["status"] == "PASS"),
                "failed": sum(1 for c in checks if c["status"] == "FAIL"),
                "warnings": sum(1 for c in checks if c["status"] == "WARN"),
            }
            
            # Overall status
            overall_ok = summary["failed"] == 0
            status_msg = "✓ All systems operational" if overall_ok else f"✗ {summary['failed']} check(s) failed"
            
            details = {
                "checks": checks,
                "summary": summary,
                "timestamp": datetime.now().isoformat(),
                "system_info": self._get_system_info(),
            }
            
            if include_logs:
                details["recent_logs"] = self._get_recent_logs()
            
            return json.dumps({
                "ok": overall_ok,
                "details": details,
                "message": status_msg
            })
        
        except Exception as e:
            return json.dumps({
                "ok": False,
                "details": {"error_trace": str(e)},
                "message": f"Diagnostic check failed: {e}"
            })
    
    # ─────────────────────────────────────────────────────────────────
    # export_diagnostic_log: Collect logs into package
    # ─────────────────────────────────────────────────────────────────
    
    def export_diagnostic_log(self, args: Dict[str, Any]) -> str:
        """Export diagnostic logs and system info into a single package.
        
        Args:
            output_path (str, optional): Path to save .tar.gz; defaults to ~/Descargas/freecad_mcp_diagnostic_TIMESTAMP.tar.gz
            include_documents (bool, optional): If True, include current FreeCAD document (risky for large models)
        
        Returns:
            JSON with {"ok": bool, "details": {...}, "message": "..."}
            
        Details:
            {
                "export_path": str,
                "file_size_bytes": int,
                "included_files": [...]
            }
        """
        try:
            import tarfile
            import shutil
            
            # Resolve output path
            if "output_path" in args and args["output_path"]:
                output_path = Path(args["output_path"])
            else:
                # Default: ~/Descargas/
                descargas = Path.home() / "Descargas"
                descargas.mkdir(exist_ok=True, parents=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_path = descargas / f"freecad_mcp_diagnostic_{timestamp}.tar.gz"
            
            # Create temp directory for staging
            temp_dir = Path("/tmp") / f"diagnostic_export_{int(time.time())}"
            temp_dir.mkdir(exist_ok=True)
            
            included_files = []
            
            # Collect files
            try:
                # 1. Debug logs
                if Path(self.DEBUG_LOG_DIR).exists():
                    logs_dest = temp_dir / "logs"
                    shutil.copytree(self.DEBUG_LOG_DIR, logs_dest)
                    included_files.append("logs/")
            except Exception as e:
                included_files.append(f"logs/ (ERROR: {e})")
            
            try:
                # 2. Operation log
                if Path(self.OPLOG_PATH).exists():
                    shutil.copy(self.OPLOG_PATH, temp_dir / "oplog.json")
                    included_files.append("oplog.json")
            except Exception as e:
                included_files.append(f"oplog.json (ERROR: {e})")
            
            try:
                # 3. Discovery info
                if Path(self.DISCOVERY_DIR).exists():
                    discovery_dest = temp_dir / "discovery"
                    shutil.copytree(self.DISCOVERY_DIR, discovery_dest)
                    included_files.append("discovery/")
            except Exception as e:
                included_files.append(f"discovery/ (ERROR: {e})")
            
            try:
                # 4. System info snapshot
                sys_info = self._get_system_info()
                with open(temp_dir / "system_info.json", "w") as f:
                    json.dump(sys_info, f, indent=2)
                included_files.append("system_info.json")
            except Exception as e:
                included_files.append(f"system_info.json (ERROR: {e})")
            
            try:
                # 5. FreeCAD process info
                proc_info = self._get_freecad_process_info()
                with open(temp_dir / "process_info.json", "w") as f:
                    json.dump(proc_info, f, indent=2)
                included_files.append("process_info.json")
            except Exception as e:
                included_files.append(f"process_info.json (ERROR: {e})")
            
            # Create tar.gz
            with tarfile.open(output_path, "w:gz") as tar:
                tar.add(temp_dir, arcname="diagnostic")
            
            # Cleanup temp dir
            shutil.rmtree(temp_dir)
            
            file_size = output_path.stat().st_size
            
            return json.dumps({
                "ok": True,
                "details": {
                    "export_path": str(output_path),
                    "file_size_bytes": file_size,
                    "file_size_mb": round(file_size / (1024 * 1024), 2),
                    "included_files": included_files,
                    "timestamp": datetime.now().isoformat(),
                },
                "message": f"Diagnostic package exported to {output_path.name}"
            })
        
        except Exception as e:
            return json.dumps({
                "ok": False,
                "details": {"error_trace": str(e)},
                "message": f"Failed to export diagnostic log: {e}"
            })
    
    # ─────────────────────────────────────────────────────────────────
    # Individual check methods
    # ─────────────────────────────────────────────────────────────────
    
    def _check_freecad_running(self) -> Dict[str, Any]:
        """Check if FreeCAD process is running."""
        try:
            import FreeCAD
            doc = FreeCAD.activeDocument()
            has_doc = doc is not None
            return {
                "name": "FreeCAD Process",
                "status": "PASS" if has_doc else "WARN",
                "details": f"FreeCAD running, active document: {doc.Name if doc else 'None'}"
            }
        except Exception as e:
            return {
                "name": "FreeCAD Process",
                "status": "FAIL",
                "details": f"Cannot import FreeCAD: {e}"
            }
    
    def _check_socket_connectivity(self) -> Dict[str, Any]:
        """Check if MCP socket is responding."""
        try:
            # Try to find and test socket
            if self._is_linux():
                sock_glob = list(Path("/tmp").glob("freecad_mcp_*.sock"))
                if not sock_glob:
                    return {
                        "name": "Socket Connectivity",
                        "status": "WARN",
                        "details": "No MCP socket found in /tmp"
                    }
                
                sock_path = str(sock_glob[0])
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(1.0)
                try:
                    sock.connect(sock_path)
                    sock.close()
                    return {
                        "name": "Socket Connectivity",
                        "status": "PASS",
                        "details": f"Socket {Path(sock_path).name} responding"
                    }
                except Exception as e:
                    return {
                        "name": "Socket Connectivity",
                        "status": "FAIL",
                        "details": f"Socket {Path(sock_path).name} not responding: {e}"
                    }
            else:
                # Windows: TCP check
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(1.0)
                    sock.connect(('localhost', 23456))
                    sock.close()
                    return {
                        "name": "Socket Connectivity",
                        "status": "PASS",
                        "details": "TCP port 23456 responding"
                    }
                except Exception as e:
                    return {
                        "name": "Socket Connectivity",
                        "status": "FAIL",
                        "details": f"TCP port 23456 not responding: {e}"
                    }
        except Exception as e:
            return {
                "name": "Socket Connectivity",
                "status": "FAIL",
                "details": f"Socket check error: {e}"
            }
    
    def _check_discovery_system(self) -> Dict[str, Any]:
        """Check discovery directory and registry."""
        try:
            discovery_path = Path(self.DISCOVERY_DIR)
            if not discovery_path.exists():
                return {
                    "name": "Discovery System",
                    "status": "WARN",
                    "details": f"Discovery dir {self.DISCOVERY_DIR} not found"
                }
            
            json_files = list(discovery_path.glob("*.json"))
            live_instances = len(json_files)
            
            return {
                "name": "Discovery System",
                "status": "PASS" if live_instances > 0 else "WARN",
                "details": f"Discovery dir exists, {live_instances} instance(s) registered"
            }
        except Exception as e:
            return {
                "name": "Discovery System",
                "status": "FAIL",
                "details": f"Discovery check error: {e}"
            }
    
    def _check_log_directory(self) -> Dict[str, Any]:
        """Check debug log directory."""
        try:
            log_path = Path(self.DEBUG_LOG_DIR)
            if not log_path.exists():
                return {
                    "name": "Log Directory",
                    "status": "WARN",
                    "details": f"Log dir {self.DEBUG_LOG_DIR} not found"
                }
            
            log_files = list(log_path.glob("*.log*")) + list(log_path.glob("*.json*"))
            total_size = sum(f.stat().st_size for f in log_files)
            
            return {
                "name": "Log Directory",
                "status": "PASS",
                "details": f"Log dir exists, {len(log_files)} files, {total_size / 1024:.1f} KB"
            }
        except Exception as e:
            return {
                "name": "Log Directory",
                "status": "FAIL",
                "details": f"Log dir check error: {e}"
            }
    
    def _check_flatpak_permissions(self) -> Dict[str, Any]:
        """Check Flatpak permissions (Linux only)."""
        try:
            # Check if running in Flatpak
            if not Path("/.flatpak-info").exists():
                return {
                    "name": "Flatpak Permissions",
                    "status": "PASS",
                    "details": "Not running in Flatpak (native install)"
                }
            
            # Check socket access
            socket_access = Path("/run/user").exists()
            return {
                "name": "Flatpak Permissions",
                "status": "PASS" if socket_access else "WARN",
                "details": "Flatpak socket access OK" if socket_access else "Limited Flatpak socket access"
            }
        except Exception as e:
            return {
                "name": "Flatpak Permissions",
                "status": "WARN",
                "details": f"Could not check Flatpak: {e}"
            }
    
    def _check_disk_space(self) -> Dict[str, Any]:
        """Check available disk space."""
        try:
            import shutil
            total, used, free = shutil.disk_usage("/")
            free_gb = free / (1024 ** 3)
            
            status = "PASS" if free_gb > 1 else "WARN" if free_gb > 0.1 else "FAIL"
            return {
                "name": "Disk Space",
                "status": status,
                "details": f"Free space: {free_gb:.2f} GB"
            }
        except Exception as e:
            return {
                "name": "Disk Space",
                "status": "WARN",
                "details": f"Could not check disk space: {e}"
            }
    
    def _check_operation_log(self) -> Dict[str, Any]:
        """Check operation log health."""
        try:
            oplog_path = Path(self.OPLOG_PATH)
            if not oplog_path.exists():
                return {
                    "name": "Operation Log",
                    "status": "WARN",
                    "details": "No operation log found"
                }
            
            with open(oplog_path) as f:
                ops = json.load(f)
            
            total_ops = len(ops)
            pending = sum(1 for o in ops if not o.get("completed"))
            
            status = "PASS" if pending == 0 else "WARN"
            details = f"Total: {total_ops}, Pending: {pending}"
            
            return {
                "name": "Operation Log",
                "status": status,
                "details": details
            }
        except Exception as e:
            return {
                "name": "Operation Log",
                "status": "WARN",
                "details": f"Could not read oplog: {e}"
            }
    
    def _benchmark_socket_latency(self) -> Dict[str, Any]:
        """Benchmark socket latency (send ping, measure round-trip)."""
        try:
            if not self._is_linux():
                return {
                    "name": "Socket Latency Benchmark",
                    "status": "WARN",
                    "details": "Benchmark only on Linux"
                }
            
            sock_glob = list(Path("/tmp").glob("freecad_mcp_*.sock"))
            if not sock_glob:
                return {
                    "name": "Socket Latency Benchmark",
                    "status": "FAIL",
                    "details": "No socket found for latency test"
                }
            
            latencies = []
            for _ in range(5):
                start = time.time()
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(1.0)
                try:
                    sock.connect(str(sock_glob[0]))
                    sock.close()
                    latencies.append((time.time() - start) * 1000)
                except:
                    pass
            
            if not latencies:
                return {
                    "name": "Socket Latency Benchmark",
                    "status": "FAIL",
                    "details": "Could not establish connection for latency test"
                }
            
            avg_latency = sum(latencies) / len(latencies)
            status = "PASS" if avg_latency < 100 else "WARN"
            
            return {
                "name": "Socket Latency Benchmark",
                "status": status,
                "details": f"Avg latency: {avg_latency:.2f}ms (5 samples)"
            }
        except Exception as e:
            return {
                "name": "Socket Latency Benchmark",
                "status": "WARN",
                "details": f"Latency test error: {e}"
            }
    
    # ─────────────────────────────────────────────────────────────────
    # Helper methods
    # ─────────────────────────────────────────────────────────────────
    
    def _is_linux(self) -> bool:
        """Check if running on Linux."""
        import platform
        return platform.system() == "Linux"
    
    def _get_system_info(self) -> Dict[str, Any]:
        """Get system information."""
        import platform
        try:
            return {
                "platform": platform.system(),
                "platform_release": platform.release(),
                "platform_version": platform.version(),
                "python_version": platform.python_version(),
                "timestamp": datetime.now().isoformat(),
            }
        except:
            return {"error": "Could not retrieve system info"}
    
    def _get_freecad_process_info(self) -> Dict[str, Any]:
        """Get FreeCAD process information."""
        try:
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True,
                text=True,
                timeout=5
            )
            freecad_procs = [line for line in result.stdout.split("\n") if "freecad" in line.lower()]
            return {
                "freecad_processes": freecad_procs,
                "process_count": len(freecad_procs)
            }
        except Exception as e:
            return {"error": f"Could not retrieve process info: {e}"}
    
    def _get_recent_logs(self, lines: int = 50) -> Dict[str, Any]:
        """Get recent log entries."""
        try:
            log_file = Path(self.DEBUG_LOG_DIR) / "freecad_mcp.log"
            if not log_file.exists():
                return {"note": "No log file found"}
            
            with open(log_file) as f:
                all_lines = f.readlines()
            
            recent = "".join(all_lines[-lines:])
            return {"recent_log_lines": recent}
        except Exception as e:
            return {"error": f"Could not read logs: {e}"}
