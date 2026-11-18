import { describe, expect, it } from 'vitest';
import {
  ACCESS_STORAGE_KEY, forgetAccess, hasRememberedAccess, rememberAccess, sha256, verifyAccessCode,
} from './access';

class Memory {
  values = new Map<string, string>();
  getItem(key: string) { return this.values.get(key) || null; }
  setItem(key: string, value: string) { this.values.set(key, value); }
  removeItem(key: string) { this.values.delete(key); }
}

describe('lightweight podcast access gate', () => {
  it('accepts only the code matching the configured digest', async () => {
    const digest = await sha256('synthetic-code');
    await expect(verifyAccessCode('synthetic-code', digest)).resolves.toBe(true);
    await expect(verifyAccessCode('wrong-code', digest)).resolves.toBe(false);
  });

  it('remembers only the digest and can relock this browser', () => {
    const memory = new Memory();
    expect(rememberAccess(memory, 'synthetic-digest')).toBe(true);
    expect(memory.getItem(ACCESS_STORAGE_KEY)).toBe('synthetic-digest');
    expect(hasRememberedAccess(memory, 'synthetic-digest')).toBe(true);
    forgetAccess(memory);
    expect(hasRememberedAccess(memory, 'synthetic-digest')).toBe(false);
  });

  it('falls back to access for the current tab when storage is unavailable', () => {
    const unavailable = {
      getItem: () => { throw new Error('disabled'); },
      setItem: () => { throw new Error('disabled'); },
      removeItem: () => { throw new Error('disabled'); },
    };
    expect(hasRememberedAccess(unavailable)).toBe(false);
    expect(rememberAccess(unavailable)).toBe(false);
    expect(() => forgetAccess(unavailable)).not.toThrow();
  });
});
