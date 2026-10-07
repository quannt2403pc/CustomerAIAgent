import js from '@eslint/js'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import globals from 'globals'
import tseslint from 'typescript-eslint'

/**
 * Luật thép L5 — không lộ JSON response ra console trình duyệt (plan.md §7.3).
 *
 * `no-console: "error"` là lớp **chặn lúc viết code**. Lớp thứ hai là
 * `esbuild.drop` trong vite.config.ts (bản production không còn lệnh console nào).
 * Lớp thứ ba là test grep trong CI (D2.12).
 *
 * Cố ý **không** cho ngoại lệ `console.error`: nếu cho, mọi chỗ cần log sẽ dùng
 * `console.error(response)` và thế là xong luật. Đường duy nhất để báo lỗi là
 * `reportError()` trong `src/lib/report-error.ts`, và hàm đó chỉ in **mã lỗi**,
 * không in body.
 */
export default tseslint.config(
  { ignores: ['dist', 'node_modules'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],

      // --- Luật thép L5 ---
      'no-console': 'error',
      'no-debugger': 'error',
      // `alert`/`confirm` chặn luồng và lộ nội dung ra ngoài UI đã thiết kế.
      'no-alert': 'error',

      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      // Dữ liệu từ API đã có kiểu riêng (src/lib/types.ts); `any` ở FE là cách
      // nhanh nhất để một field đổi tên ở BE trôi tới tận lúc chạy.
      '@typescript-eslint/no-explicit-any': 'error',
      eqeqeq: ['error', 'always'],
    },
  },
)
