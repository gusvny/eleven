/**
 * tzprobe.mjs —— wake-and-time.test.mjs 的子进程探针：钉死 TZ 后打印固定时间戳的本地「YYYY-MM-DD HH:MM」（t261004-14 起带日期）。
 */
import { localDateTime } from '../src/host/page-logic.ts'
process.stdout.write(localDateTime(Number(process.argv[2])))
