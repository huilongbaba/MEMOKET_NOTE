// 只开真能抓 bug 的规则：hooks 用法 / 依赖、未用变量、==、无用条件。风格类一条不开——
// 这仓库没有 lint 过，一上来几千条 warning 只会把真问题淹没。
import tseslint from 'typescript-eslint'
import reactHooks from 'eslint-plugin-react-hooks'

export default tseslint.config(
  { ignores: ['dist/**', 'node_modules/**', 'scripts/**', 'vite.config.*'] },
  ...tseslint.configs.recommended,
  {
    files: ['src/**/*.{ts,tsx}'],
    plugins: { 'react-hooks': reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrors: 'none' }],
      '@typescript-eslint/no-non-null-assertion': 'off',
      'eqeqeq': ['error', 'smart'],
      'no-constant-binary-expression': 'error',
    },
  },
  // 带类型信息的一条：没人接的 Promise（第 497 轮扫出 27 处——多数是 fire-and-forget 的 reload()，
  // 但也有 4 处 .then() 没 .catch，接口一失败面板就停在「加载中」）。`void x()` 表示有意不接。
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: { parserOptions: { project: './tsconfig.json', tsconfigRootDir: import.meta.dirname } },
    rules: { '@typescript-eslint/no-floating-promises': ['error', { ignoreVoid: true }] },
  },
)
