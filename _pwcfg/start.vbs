Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\baloc\Projects\aegis"
WshShell.Run """C:\Users\baloc\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\python.exe"" start.py", 0, False
