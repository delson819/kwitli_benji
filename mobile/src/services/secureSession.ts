import AsyncStorage from "@react-native-async-storage/async-storage";
import * as SecureStore from "expo-secure-store";

import { createSecureSession } from "./secureSessionCore";

const SECURE_TOKEN_KEY = "kwitli.access-token.secure";
const LEGACY_TOKEN_KEY = "kwitli.access-token";
const SECURE_OPTIONS: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};

const session = createSecureSession(
  {
    getItem: (key) => SecureStore.getItemAsync(key, SECURE_OPTIONS),
    setItem: (key, value) => SecureStore.setItemAsync(key, value, SECURE_OPTIONS),
    deleteItem: (key) => SecureStore.deleteItemAsync(key, SECURE_OPTIONS),
  },
  {
    getItem: (key) => AsyncStorage.getItem(key),
    setItem: (key, value) => AsyncStorage.setItem(key, value),
    deleteItem: (key) => AsyncStorage.removeItem(key),
  },
  SECURE_TOKEN_KEY,
  LEGACY_TOKEN_KEY,
);

export const { deleteAccessToken, getAccessToken, saveAccessToken } = session;
