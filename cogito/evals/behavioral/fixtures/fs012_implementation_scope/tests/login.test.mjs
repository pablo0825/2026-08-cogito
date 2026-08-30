import assert from 'node:assert/strict';
import test from 'node:test';
import { prepareLoginInput } from '../src/login.ts';

test('[LOGIN-NORMALIZED] preserves an already normalized email', () => {
  assert.deepEqual(prepareLoginInput('ada@example.com', 'secret'), {
    email: 'ada@example.com', password: 'secret',
  });
});

test('[LOGIN-PASSWORD] preserves every password character', () => {
  const password = '  Secret\t\n密碼  ';
  assert.equal(prepareLoginInput('ada@example.com', password).password, password);
});
