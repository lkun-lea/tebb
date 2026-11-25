import { BookOpen, CalendarDays, CheckSquare, Code, FileText, Folder, GitBranch, Globe, Layers, ListChecks, MemoryStick, NotebookPen, Play, Search, Terminal, Video, Wrench } from 'lucide-react';

const copy: Record<string,[string,string,typeof Wrench]> = {
  get_today_agenda:['今日日程','查看今天的飞书日历安排。',CalendarDays],
  get_open_tasks:['到期待办','列出今天到期和已逾期的飞书待办。',CheckSquare],
  calendar_propose:['起草日程','先预览时间和主题，再决定是否保存。',CalendarDays],
  calendar_create:['创建日程','把约定的时间和主题加入日历。',CalendarDays],
  github_status:['GitHub 连接状态','检查账号连接和未归档仓库的状态。',GitBranch],
  github_roadmap:['仓库路线图','查看里程碑中尚未完成的事项。',GitBranch],
  github_recent:['仓库近况','回顾近 14 天的提交、合并请求和议题。',GitBranch],
  github_repository:['浏览仓库','查看已授权仓库的说明、目录和源码。',Folder],
  read_recent_errors:['最近错误','查阅本机后端最近的错误记录。',Code],
  list_skills:['浏览技能','查找已安装的技能及适用场景。',Layers],
  read_skill:['阅读技能说明','打开一项技能的完整使用步骤。',BookOpen],
  remember_fact:['记住信息','保存你希望 tebb 记住的事实或偏好。',MemoryStick],
  forget_fact:['停用记忆','让 tebb 今后停止引用指定记忆。',MemoryStick],
  read_local_source:['阅读附件','查看已选文件的内容或文件夹清单。',FileText],
  execute_command:['运行沙箱命令','在当前会话的隔离 Linux 环境运行命令。',Terminal],
  read_terminal_output:['查看命令输出','继续阅读已运行命令的输出。',Terminal],
  web_search:['搜索网页','查找最新资料和来源链接。',Globe],
  read_video:['读取视频','查看公开视频的信息、章节和可用字幕。',Video],
  read_video_transcript:['阅读视频字幕','继续阅读当前视频的字幕原文。',Video],
  save_video_summary:['保存视频笔记','把当前视频的总结保存为飞书文档。',NotebookPen],
  self_test_catalog:['自测目录','查找可运行的测试和所需条件。',ListChecks],
  self_test_start:['运行自测','用隔离样例验证一项 tebb 能力。',Play],
  self_test_inspect:['查看自测报告','查看自测进度、结果和失败线索。',Search],
  self_test_cancel:['停止自测','取消当前任务发起的自测。',ListChecks]
};
const sections:Record<string,string> = {
  get_today_agenda:'日历与待办',get_open_tasks:'日历与待办',calendar_create:'日历与待办',calendar_propose:'日历与待办',
  remember_fact:'记忆与技能',forget_fact:'记忆与技能',list_skills:'记忆与技能',read_skill:'记忆与技能',
  execute_command:'文件与终端',read_terminal_output:'文件与终端',read_local_source:'文件与终端',
  web_search:'搜索与视频',read_video:'搜索与视频',read_video_transcript:'搜索与视频',save_video_summary:'搜索与视频',
  read_recent_errors:'诊断与自测',self_test_catalog:'诊断与自测',self_test_start:'诊断与自测',self_test_cancel:'诊断与自测',self_test_inspect:'诊断与自测'
};
export function toolPresentation(d:{name:string;description:string;collection:string;capabilityId?:string}) {
  const fallback = d.description.split(/[。；;\n]/)[0].trim();
  const [title,summary,Icon] = (!d.capabilityId && copy[d.name]) || [
    d.capabilityId ? d.name : fallback.length > 0 && fallback.length <= 16 ? fallback : d.name.replaceAll('_',' '),
    fallback || d.collection, d.capabilityId ? Layers : Wrench
  ];
  return {title,summary,Icon,group:(!d.capabilityId && sections[d.name]) || d.collection};
}
