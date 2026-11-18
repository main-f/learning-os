export const ACCESS_DIGEST = 'b9b316fb4fc3ffdc0e49a93f998a12bff0d00a83bbb19c4475ee93eef6b4254d';
export const ACCESS_STORAGE_KEY = 'rae-podcast-access-v1';

type AccessStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

export async function sha256(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

export async function verifyAccessCode(code: string, expected = ACCESS_DIGEST): Promise<boolean> {
  return await sha256(code) === expected;
}

export function hasRememberedAccess(storage: AccessStorage, expected = ACCESS_DIGEST): boolean {
  try { return storage.getItem(ACCESS_STORAGE_KEY) === expected; }
  catch { return false; }
}

export function rememberAccess(storage: AccessStorage, expected = ACCESS_DIGEST): boolean {
  try {
    storage.setItem(ACCESS_STORAGE_KEY, expected);
    return true;
  } catch { return false; }
}

export function forgetAccess(storage: AccessStorage): void {
  try { storage.removeItem(ACCESS_STORAGE_KEY); } catch { /* Current tab still locks. */ }
}
