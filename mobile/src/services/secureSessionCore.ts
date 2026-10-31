export type SessionStore = {
  getItem(key: string): Promise<string | null>;
  setItem(key: string, value: string): Promise<void>;
  deleteItem(key: string): Promise<void>;
};

export function createSecureSession(
  secureStore: SessionStore,
  legacyStore: SessionStore,
  secureKey: string,
  legacyKey: string,
) {
  return {
    async saveAccessToken(token: string): Promise<void> {
      await secureStore.setItem(secureKey, token);
      await legacyStore.deleteItem(legacyKey);
    },

    async getAccessToken(): Promise<string | null> {
      const secureToken = await secureStore.getItem(secureKey);
      if (secureToken) return secureToken;

      const legacyToken = await legacyStore.getItem(legacyKey);
      if (!legacyToken) return null;

      await secureStore.setItem(secureKey, legacyToken);
      await legacyStore.deleteItem(legacyKey);
      return legacyToken;
    },

    async deleteAccessToken(): Promise<void> {
      await Promise.all([
        secureStore.deleteItem(secureKey),
        legacyStore.deleteItem(legacyKey),
      ]);
    },
  };
}
