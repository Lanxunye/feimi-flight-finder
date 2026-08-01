/* eslint-disable @typescript-eslint/no-require-imports */
const os = require("node:os");

const runtimeStateDirectory = process.env.FEIMI_RUNTIME_STATE_DIR;
if (runtimeStateDirectory) {
  os.homedir = () => runtimeStateDirectory;
}
