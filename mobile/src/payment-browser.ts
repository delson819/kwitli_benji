import * as ExpoLinking from "expo-linking";
import * as WebBrowser from "expo-web-browser";
import { Linking, Platform } from "react-native";

// Le resultat du navigateur est seulement un retour, jamais une preuve de paiement.
export async function openFlutterwaveBrowser(url: string): Promise<string | null> {
  const returnUrl = ExpoLinking.createURL("payment-return");
  if (!returnUrl.startsWith("kwitli://")) {
    // Expo Go n'a pas le scheme natif Kwitli : l'onglet Android se ferme manuellement.
    if (Platform.OS === "android") await WebBrowser.openBrowserAsync(url);
    else await Linking.openURL(url);
    return null;
  }
  const result = await WebBrowser.openAuthSessionAsync(url, returnUrl);
  return result.type === "success" ? result.url : null;
}
