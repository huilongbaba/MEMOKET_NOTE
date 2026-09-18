/// <reference types="vite/client" />
// Vite 模板的标配文件：让 `import x from './a.css?raw'` 这类带查询串的导入有类型。
// P10 的闸（`__tests__/p10Editor.test.ts`）用它把 styles.css / App.tsx 当字符串读进来核对令牌和分支——
// src 下没有 node 的类型，读不了 `node:fs`。
