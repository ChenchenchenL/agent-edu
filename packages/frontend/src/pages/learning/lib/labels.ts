export function hintLevelLabel(level: string): string {
  switch (level) {
    case "conceptual":
      return "概念提示";
    case "scaffolded":
      return "步骤引导";
    case "targeted":
      return "针对性提示";
    default:
      return level;
  }
}

export function difficultyLabel(level: string): string {
  switch (level) {
    case "easy":
      return "简单";
    case "medium":
      return "中等";
    case "hard":
      return "困难";
    default:
      return level;
  }
}

export function taskStatusLabel(status: string): string {
  switch (status) {
    case "pending":
      return "待执行";
    case "in_progress":
      return "进行中";
    case "completed":
      return "已完成";
    case "failed":
      return "失败";
    case "skipped":
      return "已跳过";
    case "review":
      return "待复习";
    case "due":
      return "已到期";
    default:
      return status;
  }
}

export function taskTypeLabel(type: string): string {
  switch (type) {
    case "study":
      return "学习";
    case "practice":
      return "练习";
    case "assessment":
      return "测评";
    case "review":
      return "复习";
    case "milestone":
      return "里程碑";
    default:
      return type;
  }
}
