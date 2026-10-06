# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['D:/votumsecuris/loader.py'],
    pathex=[],
    binaries=[],
    datas=[('D:/votumsecuris/registry/tools.yaml', 'registry'), ('D:/votumsecuris/policy/rules.yaml', 'policy'), ('D:/votumsecuris/audit/init.sql', 'audit'), ('D:/votumsecuris/memory/init.sql', 'memory'), ('D:/votumsecuris/knowledge/README.md', 'knowledge')],
    hiddenimports=['yaml', 'sqlite3', 'memory.rag', 'memory.version', 'memory.perf_log', 'policy.engine', 'policy.honesty', 'policy.idle_code', 'executor.llm_control', 'executor.safe_delete', 'executor.policy_bridge', 'sync.server', 'sync.client', 'identity.agent_id', 'identity.permission', 'identity.audit'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='VotumSecuris',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
