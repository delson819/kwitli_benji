import { createSecureSession, type SessionStore } from "./services/secureSessionCore.ts";

class MemoryStore implements SessionStore {
  readonly values = new Map<string, string>();

  async getItem(key: string): Promise<string | null> {
    return this.values.get(key) ?? null;
  }

  async setItem(key: string, value: string): Promise<void> {
    this.values.set(key, value);
  }

  async deleteItem(key: string): Promise<void> {
    this.values.delete(key);
  }
}

function expect(condition: boolean): void {
  if (!condition) throw new Error("Secure session assertion failed.");
}

const secure = new MemoryStore();
const legacy = new MemoryStore();
const session = createSecureSession(secure, legacy, "secure", "legacy");

expect(await session.getAccessToken() === null);
await session.saveAccessToken("login-token");
expect(secure.values.get("secure") === "login-token");
expect(await session.getAccessToken() === "login-token");
await session.deleteAccessToken();
expect(await session.getAccessToken() === null);

legacy.values.set("legacy", "old-token");
expect(await session.getAccessToken() === "old-token");
expect(secure.values.get("secure") === "old-token");
expect(!legacy.values.has("legacy"));
