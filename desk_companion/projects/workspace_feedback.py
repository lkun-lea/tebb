"""Actionable, non-sensitive failure reasons for model-facing workspace reads."""


def read_error(exc):
    message = str(exc)
    reasons = (
        (('保护', '链接', '授权已变化'), 'access_denied', '核对当前工作区授权范围。'),
        (('未知的工作区根标识',), 'invalid_root', '使用主目录时省略 root；参考目录使用已绑定的 ref-N。'),
        (('尚未配置',), 'workspace_unbound', '请用户绑定项目目录。'),
        (('目标是文件', '目标是目录'), 'wrong_path_type', '目录用 workspace_list，文件用 workspace_read。'),
        (('文件不存在', '目录不存在', '搜索路径不存在'), 'path_not_found', '先列出父目录，核对路径和类型。'),
        (('行号', '搜索词', '参数', '符号'), 'invalid_selector', '核对搜索模式、符号或行号后重试。'),
        (('预览', 'UTF-8'), 'unsupported_preview', '核对文件类型、编码或大小。'),
    )
    if isinstance(exc, PermissionError):
        return dict(reason='access_denied', next_action='检查目录读取权限。')
    for markers, reason, action in reasons:
        if any(marker in message for marker in markers):
            return dict(reason=reason, next_action=action)
    return dict(reason='workspace_read_failed', next_action='检查读取回执；无法确认内容。')
