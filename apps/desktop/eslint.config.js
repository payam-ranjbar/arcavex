import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import typescript from "typescript-eslint";

export default typescript.config(
  // Generated or build output: coverage and bundle-verification appear only after a
  // local run, and linting them fails on files no tsconfig owns.
  {
    ignores: [
      "dist/**",
      "coverage/**",
      "bundle-verification/**",
      "src-tauri/target/**",
      "src/contracts/generated*.ts",
    ],
  },
  js.configs.recommended,
  ...typescript.configs.recommendedTypeChecked,
  {
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
      parserOptions: {
        projectService: { allowDefaultProject: ["eslint.config.js"] },
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "@typescript-eslint/consistent-type-imports": "error",
      "@typescript-eslint/no-unnecessary-condition": "error",
      // A leading underscore is how this codebase says "deliberately discarded".
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      "no-restricted-syntax": [
        "error",
        {
          selector: "TSAsExpression > TSAnyKeyword",
          message: "Casting to any erases the generated engine contracts.",
        },
      ],
    },
  },
  {
    // The gateway adapter is the boundary where untyped Tauri payloads become typed reports.
    files: ["src/gateway/TauriArcavexGateway.ts"],
    rules: { "@typescript-eslint/no-unsafe-return": "off" },
  },
  {
    files: ["**/*.test.ts", "**/*.test.tsx", "src/shared/test/**"],
    rules: { "@typescript-eslint/no-unsafe-assignment": "off" },
  },
);
