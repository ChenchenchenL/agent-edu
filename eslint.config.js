const { defineConfig } = require("eslint/config");
const js = require("@eslint/js");
const tseslint = require("typescript-eslint");

module.exports = defineConfig([
  {
    name: "global-ignores",
    ignores: [
      "**/node_modules/**",
      "**/dist/**",
      "**/build/**",
      "**/coverage/**",
      "**/.cache/**",
      "**/.venv/**",
      "**/venv/**",
      "**/__pycache__/**",
    ],
  },
  {
    name: "js-ts-base",
    files: ["**/*.js", "**/*.mjs", "**/*.cjs", "**/*.ts", "**/*.mts", "**/*.cts"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
    },
    rules: {
      curly: ["error", "all"],
      eqeqeq: ["error", "always"],
      "no-debugger": "error",
      "no-console": "off",
      "prefer-const": "error",
    },
  },
  {
    name: "commonjs-overrides",
    files: ["**/*.cjs", "**/*.cts"],
    languageOptions: {
      sourceType: "commonjs",
    },
  },
  {
    name: "javascript-overrides",
    files: ["**/*.js", "**/*.mjs", "**/*.cjs"],
    rules: {
      "no-unused-vars": ["warn", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
    },
  },
  {
    name: "typescript-overrides",
    files: ["**/*.ts", "**/*.mts", "**/*.cts"],
    rules: {
      "no-unused-vars": "off",
      "@typescript-eslint/consistent-type-imports": [
        "warn",
        { prefer: "type-imports", fixStyle: "separate-type-imports" },
      ],
      "@typescript-eslint/no-unused-vars": [
        "warn",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
]);
