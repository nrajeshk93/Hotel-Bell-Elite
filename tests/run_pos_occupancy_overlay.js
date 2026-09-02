const fs = require("fs");
const vm = require("vm");
const src = fs.readFileSync(process.argv[2], "utf8");
const input = JSON.parse(process.argv[3]);
const store = {};
const ctx = {
  console,
  indexedDB: undefined,
  BroadcastChannel: undefined,
  navigator: { onLine: true },
  document: undefined,
  localStorage: {
    getItem(k) {
      return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null;
    },
    setItem(k, v) {
      store[k] = String(v);
    },
    removeItem(k) {
      delete store[k];
    }
  }
};
ctx.sessionStorage = ctx.localStorage;
ctx.window = ctx;
ctx.self = ctx;
vm.createContext(ctx);
vm.runInContext(src, ctx);
const api = ctx.HbePosOffline;
if (!api || typeof api.applyUnsyncedOrdersToFloorTables !== "function") {
  process.stderr.write("missing applyUnsyncedOrdersToFloorTables\n");
  process.exit(2);
}
const out = api.applyUnsyncedOrdersToFloorTables(
  input.tables,
  input.orders,
  input.want || "restaurant"
);
process.stdout.write(JSON.stringify(out));
