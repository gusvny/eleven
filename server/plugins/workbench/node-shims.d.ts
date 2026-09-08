/**
 * node-shims.d.ts —— 宿主半（node.ts / src/host/changes.ts）的 node 内建模块
 * 最小类型声明（制式照 server/plugins/knowledge/node-shims.d.ts）。
 *
 * 为什么存在：本插件不设 node_modules（仓库红线：不引入新依赖），tsconfig 的
 * paths 只借了 /tmp/wb-deps 的 react/dsh 类型，没有 @types/node。这里按实际
 * 用到的 API 面声明最小签名，浏览器半 bundle 不含本文件。
 */

declare module 'node:child_process' {
  export function execFile(
    file: string, args: string[],
    options: { cwd?: string; timeout?: number },
    callback: (error: Error | null, stdout: string, stderr: string) => void,
  ): unknown
  /** t260827-02 补：epic-next.ts spawn 一次性 headless agent（detached 长任务，poll 判活）。
   *  t260828-03 补：signalCode（kill 后判死）与 unref（stub 哑进程不拖宿主退出）。 */
  export interface ChildProcess {
    readonly exitCode: number | null
    readonly signalCode: string | null
    kill(signal?: string): boolean
    unref(): void
    on(event: 'error', listener: (err: Error) => void): void
  }
  export function spawn(
    file: string, args: string[],
    options: { cwd?: string; env?: Record<string, string | undefined>; stdio?: unknown },
  ): ChildProcess
}

declare module 'node:crypto' {
  export function randomUUID(): string
}

declare module 'node:fs/promises' {
  export function readFile(path: string, encoding: 'utf8'): Promise<string>
  export function readdir(path: string): Promise<string[]>
  /** M14 补：_sessionKbFast（agent-logs.ts）按目录遍历 session 文件（370fd42 引入用法，
   *  但 node-shims.d.ts 未同步声明 → tsc 报「Expected 1 arguments」）。 */
  export function readdir(path: string, options: { withFileTypes: true }): Promise<Dirent[]>
  export function stat(path: string): Promise<{ size: number; mtimeMs: number; isDirectory(): boolean }>
  export function mkdir(path: string, options?: { recursive?: boolean }): Promise<void>
  export function writeFile(path: string, data: string, encoding?: 'utf8'): Promise<void>
  export function appendFile(path: string, data: string, encoding?: 'utf8'): Promise<void>
  /** t260827-02 补：epic-next.ts 拷 profile/creds/settings 与清理过期 job 目录。 */
  export function cp(src: string, dst: string, options?: { recursive?: boolean }): Promise<void>
  export function rm(path: string, options?: { recursive?: boolean; force?: boolean }): Promise<void>
}

/** t260827-02 补：epic-next.ts 同步探测（existsSync）与 agent.log 文件描述符（openSync）。 */
declare module 'node:fs' {
  export function existsSync(path: string): boolean
  export function openSync(path: string, flags: string): number
}

/** t260827-02 补：epic-next.ts 解析用户级 ~/.dsh（DSH_HOME 缺省值）。 */
declare module 'node:os' {
  export function homedir(): string
}

/** fs.Dirent 最小面（readdir withFileTypes 的元素）。 */
interface Dirent {
  name: string
  isDirectory(): boolean
}

declare module 'node:http' {
  export interface IncomingMessage {
    url?: string
    method?: string
    [Symbol.asyncIterator](): AsyncIterableIterator<Buffer>
  }
  export interface ServerResponse {
    writeHead(statusCode: number, headers: Record<string, string>): void
    end(body?: string): void
  }
}

declare module 'node:net' {
  interface Socket {
    setTimeout(ms: number): void
    once(event: 'connect' | 'error' | 'timeout', listener: () => void): void
    destroy(): void
  }
  export function connect(options: { host: string; port: number }): Socket
  const net: { connect: typeof connect }
  export default net
}

declare module 'node:path' {
  export function dirname(p: string): string
  export function join(...paths: string[]): string
  export function resolve(...paths: string[]): string
  export const sep: string
}

declare module 'node:url' {
  export function fileURLToPath(url: string | URL): string
}

declare module 'node:util' {
  export function promisify(fn: unknown): any
}

interface Buffer {
  length: number
  toString(encoding: 'utf8'): string
}
declare const Buffer: {
  concat(chunks: Buffer[]): Buffer
}
declare const process: {
  env: Record<string, string | undefined>
  kill(pid: number, signal?: number): void
  /** t260828-03 补：epic-next.ts stub 哑进程 spawn（process.execPath -e ...）。 */
  execPath: string
}
