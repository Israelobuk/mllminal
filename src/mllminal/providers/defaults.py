"""Construct the standard provider set for the desktop runtime."""

from pathlib import Path

from mllminal.apps.browser_bridge import BrowserBridge
from mllminal.providers.email import (
    BrowserEmailProvider,
    ClassicOutlookProvider,
    ModernOutlookProvider,
    SystemMailComposeProvider,
)
from mllminal.providers.resolver import CapabilityResolver
from mllminal.providers.spreadsheets import (
    BrowserSpreadsheetProvider,
    ExcelDesktopProvider,
    LibreOfficeProvider,
    ManualSpreadsheetHandoffProvider,
    PythonSpreadsheetInspectionProvider,
)


def create_default_resolver(database_path: Path, workspace_root: Path) -> CapabilityResolver:
    data_dir = database_path.parent / "providers"
    browser_bridge = BrowserBridge()
    return CapabilityResolver(
        [
            ExcelDesktopProvider(workspace_root, data_dir / "excel"),
            ClassicOutlookProvider(workspace_root, data_dir / "email"),
            ModernOutlookProvider(),
            BrowserSpreadsheetProvider(browser_bridge),
            BrowserEmailProvider(browser_bridge),
            PythonSpreadsheetInspectionProvider(),
            LibreOfficeProvider(),
            ManualSpreadsheetHandoffProvider(),
            SystemMailComposeProvider(),
        ]
    )
