/**
 * project-modals-types.ts —— 弹层消费的注册表条目最小形状（与 sidebar Project
 * 接口同源字段；独立小文件避免 client 测试缝引整棵 sidebar）。
 */
export interface ProjectEntryLike {
  key: string
  name: string
  primary: string
}
