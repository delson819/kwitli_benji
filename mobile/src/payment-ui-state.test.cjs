const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');

const outputExports = {};
const source = fs.readFileSync(`${__dirname}/payment-ui-state.ts`, 'utf8');
vm.runInNewContext(ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, { exports: outputExports });
const { resolvePaymentUiState } = outputExports;
const makePayment = (status) => ({ id: 'payment-test', status });

assert.equal(resolvePaymentUiState(null, false, true), 'idle');
assert.equal(resolvePaymentUiState(null, true, false), 'redirecting');
assert.equal(resolvePaymentUiState(makePayment('pending'), false, false), 'verifying');
assert.equal(resolvePaymentUiState(makePayment('approved'), true, true), 'approved');
assert.equal(resolvePaymentUiState(makePayment('declined'), false, false), 'failed');
for (const status of ['paid_stock_conflict', 'reconcile_required', 'refund_pending', 'refunded', 'future_status']) {
  assert.equal(resolvePaymentUiState(makePayment(status), false, false), 'resolution_required', status);
}
