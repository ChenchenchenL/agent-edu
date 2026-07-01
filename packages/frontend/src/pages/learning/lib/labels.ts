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
