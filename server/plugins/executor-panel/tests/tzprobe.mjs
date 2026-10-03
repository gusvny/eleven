/**
 * tzprobe.mjs —— wake-and-time.test.mjs 的子进程探针：钉死 TZ 后打印固定时间戳的本地 HH:MM。
 */
import { hhmmLocal } from '../src/host/page-logic.ts'
process.stdout.write(hhmmLocal(Number(process.argv[2])))
