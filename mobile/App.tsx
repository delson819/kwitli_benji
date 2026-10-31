import { useEffect, useRef, useState } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import {
  ActivityIndicator,
  Alert,
  AppState,
  Image,
  Linking,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  useWindowDimensions,
  View,
} from "react-native";
import { Fraunces_600SemiBold } from "@expo-google-fonts/fraunces/600SemiBold";
import { Fraunces_700Bold } from "@expo-google-fonts/fraunces/700Bold";
import { Manrope_400Regular } from "@expo-google-fonts/manrope/400Regular";
import { Manrope_500Medium } from "@expo-google-fonts/manrope/500Medium";
import { Manrope_600SemiBold } from "@expo-google-fonts/manrope/600SemiBold";
import { Manrope_700Bold } from "@expo-google-fonts/manrope/700Bold";
import { Manrope_800ExtraBold } from "@expo-google-fonts/manrope/800ExtraBold";
import Ionicons from "@expo/vector-icons/Ionicons";
import { useFonts } from "expo-font";
import { StatusBar } from "expo-status-bar";
import * as ExpoLinking from "expo-linking";
import * as Device from "expo-device";
import * as ImageManipulator from "expo-image-manipulator";
import * as ImagePicker from "expo-image-picker";
import * as Location from "expo-location";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";

import { AppHeader } from "./src/components/AppHeader";
import { LocationPickerModal } from "./src/components/LocationPickerModal";
import { BrandSplash } from "./src/components/BrandSplash";
import { ClientWelcome } from "./src/components/ClientWelcome";
import { ClientReviewForm } from "./src/components/ClientReviewForm";
import { ClientProfile } from "./src/components/ClientProfile";
import { PublicBusinessProfile } from "./src/components/PublicBusinessProfile";
import { MerchantDashboard } from "./src/components/MerchantDashboard";
import { menuArticle } from "./src/client-menu";
import { BottomNavigation, type ClientTab } from "./src/components/BottomNavigation";
import { BusinessDiscoveryCard } from "./src/components/BusinessDiscoveryCard";
import { DishDetail } from "./src/components/DishDetail";
import { CartBar } from "./src/components/CartBar";
import { CartScreen } from "./src/components/CartScreen";
import { CartSummary } from "./src/components/CartSummary";
import { ExploreFartherScreen } from "./src/components/ExploreFartherScreen";
import { FilterChip } from "./src/components/FilterChip";
import { HomeSkeleton } from "./src/components/HomeSkeleton";
import { HomeState } from "./src/components/HomeState";
import { groupDiscoverItemsByBusiness } from "./src/client-content";
import { PrimaryButton } from "./src/components/PrimaryButton";
import { API_URL, mediaUrl } from "./src/config";
import { DEFAULT_BUSINESS_VERTICAL, VISIBLE_CLIENT_VERTICALS, homeDiscoveryRadius, shouldShowHomeCauldron } from "./src/discovery";
import { formatMoney } from "./src/format";
import { t, type TranslationKey } from "./src/i18n";
import { ACTIVE_MARKET } from "./src/market";
import {
  activeServiceAreaLabels,
  clearManualLocationChoice,
  locationHomeMessageKind,
  parseLocationChoice,
  restoreManualLocationChoice,
  resolveLocation,
  shouldAcceptSimulatedPosition,
  shouldRefreshLocationAfterResume,
  shouldRequestForegroundPermission,
  saveManualLocationChoice,
  type Coordinates,
  type DetectedDevicePosition,
  type LocationChoice,
  type LocationFailureReason,
  type LocationSource,
  type ServiceArea,
} from "./src/location";
import { addCartItem, canOrderQuantity, cartItemId, changeCartQuantity, removeCartItem, requiresCartReplacement, hasMixedCartCurrency, type CartItem } from "./src/order-actions";
import { validQuantity } from "./src/payment-flow";
import { paymentIdentityFromReturn } from "./src/payment-return";
import { passwordResetTokenFromUrl } from "./src/auth-recovery";
import { assessMerchantServiceArea, validateMerchantGpsFix } from "./src/merchant-location";
import { openFlutterwaveBrowser } from "./src/payment-browser";
import { checkoutPaymentKey, clearCheckoutPayment, loadCheckoutPayment, saveCheckoutPayment, readExistingPayment, newCheckoutSession, sameCheckout, sameCart, paymentMatchesCheckout, paymentIdempotencyKey, completeCheckoutPayment, type StoredPaymentSession, type PaymentIdentity } from "./src/payment-session";
import { OrdersScreen } from "./src/components/OrdersScreen";
import {
  addFavorite,
  ApiError,
  createAvailability,
  createDish,
  createCook,
  createPayment,
  createReview,
  getAvailabilities,
  getDiscover,
  getDishes,
  getApiHealth,
  getFavoriteStatus,
  getFavorites,
  getCookBusinessHours,
  getMe,
  getServiceAreas,
  getPayment,
  getPaymentByReference,
  getOrder,
  logAuthDiagnostic,
  paySandboxInvoice,
  getPublicCook,
  login,
  requestPasswordReset,
  confirmPasswordReset,
  paymentCheckoutUrl,
  register,
  removeFavorite,
  saveCookBusinessHours,
  setAccessToken,
  updateAvailability,
  updateCook,
  updateDish,
  uploadCookProfilePhoto,
  uploadDishPhoto,
  type Availability,
  type BusinessHour,
  type BusinessVertical,
  type DiscoverFilter,
  type DiscoverItem,
  type Dish,
  type FavoriteCook,
  type Me,
  type OrderHistory,
  type Payment,
  type PublicCookProfile,
} from "./src/services/api";
import { deleteAccessToken, getAccessToken, saveAccessToken } from "./src/services/secureSession";
import { colors } from "./src/theme/colors";
import { breakpoints, controlSizes } from "./src/theme/layout";
import { radius } from "./src/theme/radius";
import { spacing } from "./src/theme/spacing";
import { fontSizes, fonts, lineHeights } from "./src/theme/typography";

type Mode = "client" | "cook";
type Screen = "discover" | "exploreFarther" | "favorites" | "orders" | "cookProfile" | "account" | "cart" | "cartSummary";
type DiscoverErrorKind = "location" | "network" | "server" | "request";

const SPLASH_MINIMUM_VISIBLE_MS = 900;
const BOOTSTRAP_RESTORE_TIMEOUT_MS = 3500;
const MAX_MERCHANT_PHOTO_DIMENSION = 1600;

function safeLocationErrorDetails(error: unknown): { errorType: string; errorCode?: string } {
  if (!error || typeof error !== "object") return { errorType: "UnknownError" };
  const candidate = error as { name?: unknown; code?: unknown };
  const errorType = typeof candidate.name === "string" && /^[A-Za-z][A-Za-z0-9_]{0,39}$/.test(candidate.name)
    ? candidate.name
    : "UnknownError";
  const errorCode = typeof candidate.code === "string" && /^E_[A-Z0-9_]{1,48}$/.test(candidate.code)
    ? candidate.code
    : undefined;
  return { errorType, ...(errorCode ? { errorCode } : {}) };
}

function locationIssueMessage(reason: LocationFailureReason | null, activeAreas: ServiceArea[] = []): string {
  switch (reason) {
    case "permission_denied": return t("location.permissionDenied");
    case "permission_blocked": return t("location.permissionBlocked");
    case "services_disabled": return t("location.servicesDisabled");
    case "gps_timeout": return t("location.timeout");
    case "gps_error": return t("location.nativeError");
    case "invalid_coordinates": return t("location.invalidPosition");
    case "stale_fix": return t("location.stalePosition");
    case "missing_accuracy": return t("location.accuracyUnavailable");
    case "low_accuracy": return t("location.accuracyTooLow");
    case "outside_active_areas": {
      const areaNames = activeServiceAreaLabels(activeAreas);
      if (areaNames.length === 1) return t("location.outsideOneServiceArea", { area: areaNames[0] });
      if (areaNames.length > 1) return t("location.outsideSeveralServiceAreas", { areas: areaNames.join(", ") });
      return t("location.outsideServiceAreas");
    }
    case "no_active_service_areas": return "";
    case "gps_unavailable": return t("location.unavailable");
    default: return "";
  }
}

const VERTICAL_EMPTY_TITLES: Record<BusinessVertical, TranslationKey> = {
  food_service: "home.emptyTitle.foodService",
  bakery_dessert: "home.emptyTitle.bakeryDessert",
  local_shop: "home.emptyTitle.localShop",
};

const VERTICAL_LABELS: Record<BusinessVertical, TranslationKey> = {
  food_service: "home.vertical.foodService",
  bakery_dessert: "home.vertical.bakeryDessert",
  local_shop: "home.vertical.localShop",
};

function nextAvailabilityDate(): string {
  const date = new Date();
  date.setDate(date.getDate() + 1);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function errorMessage(error: unknown, review = false): string {
  if (!(error instanceof ApiError)) return t("error.generic");
  if (error.message === "API_URL_NOT_CONFIGURED") return t("error.config");
  if (error.status === 0) return t("error.network");
  if (error.status === 400) return t("error.http400");
  if (error.status === 401) return t("error.auth");
  if (error.status === 403) return t("errors.forbidden");
  if (error.status === 404) return t("error.http404");
  if (error.status === 422) return t("error.http422");
  if (error.status === 429) return t("error.http429");
  if (error.status >= 500) return t("error.http500");
  if (review) return t("errors.review");
  return error.status === 409 ? t("error.stock") : t("error.generic");
}

function merchantPhotoUploadErrorMessage(error: unknown): string {
  return error instanceof ApiError && error.status === 415
    ? t("error.imageFormat")
    : t("error.imageUpload");
}

function Input({
  label,
  value,
  onChangeText,
  numeric,
  secure,
}: {
  label: string;
  value: string;
  onChangeText: (value: string) => void;
  numeric?: boolean;
  secure?: boolean;
}) {
  return (
    <View style={styles.field}>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        value={value}
        onChangeText={onChangeText}
        secureTextEntry={secure}
        keyboardType={numeric ? "decimal-pad" : "default"}
        style={styles.input}
      />
    </View>
  );
}

function Photo({ uri, large = false, client = false }: { uri: string | null; large?: boolean; client?: boolean }) {
  if (uri) return <Image source={{ uri: mediaUrl(uri) }} style={large ? styles.photoLarge : styles.photo} />;
  return (
    <View style={large ? styles.photoLarge : styles.photo}>
      <Ionicons color={colors.brandGreen} name="restaurant-outline" size={large ? 32 : 22} />
      <Text style={styles.photoPlaceholderText}>{t(client ? "clientExperience.photoTitle" : "photo.placeholderTitle")}</Text>
    </View>
  );
}

function money(value: string, currency: string): string {
  return formatMoney(value, currency);
}

function confirmPayTechTest(provider: string | undefined): Promise<boolean> {
  if (provider !== "paytech") return Promise.resolve(true);
  return new Promise((resolve) => Alert.alert(t("checkout.paytechTitle"), t("checkout.paytechWarning"), [
    { text: t("checkout.paytechCancel"), style: "cancel", onPress: () => resolve(false) },
    { text: t("checkout.paytechContinue"), onPress: () => resolve(true) },
  ], { cancelable: true, onDismiss: () => resolve(false) }));
}

export default function App() {
  const [fontsLoaded, fontError] = useFonts({
    Fraunces_600SemiBold,
    Fraunces_700Bold,
    Manrope_400Regular,
    Manrope_500Medium,
    Manrope_600SemiBold,
    Manrope_700Bold,
    Manrope_800ExtraBold,
  });

  return (
    <SafeAreaProvider>
      <KwitliApp fontsReady={fontsLoaded || Boolean(fontError)} />
    </SafeAreaProvider>
  );
}

function KwitliApp({ fontsReady }: { fontsReady: boolean }) {
  const { width: viewportWidth } = useWindowDimensions();
  const mainScrollRef = useRef<ScrollView>(null);
  const menuRequest = useRef(0);
  const detailProfileReturn = useRef<PublicCookProfile | null>(null);
  const cartActionLock = useRef(false);
  const [me, setMe] = useState<Me | null>(null);
  const [restoring, setRestoring] = useState(true);
  const [welcomeDismissed, setWelcomeDismissed] = useState(false);
  const [splashMinimumElapsed, setSplashMinimumElapsed] = useState(false);
  const [splashVisible, setSplashVisible] = useState(true);
  const [mode, setMode] = useState<Mode>("client");
  const [screen, setScreen] = useState<Screen>("discover");

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [registering, setRegistering] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [apiHealthProbeBusy, setApiHealthProbeBusy] = useState(false);
  const [apiHealthProbeResult, setApiHealthProbeResult] = useState<
    | { kind: "http"; status: number }
    | { kind: "http_error"; status: number }
    | { kind: "response_error"; status: number }
    | { kind: "network_error"; errorType: string }
    | null
  >(null);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [passwordResetStep, setPasswordResetStep] = useState<"idle" | "request" | "confirm">("idle");
  const [passwordResetEmail, setPasswordResetEmail] = useState("");
  const [passwordResetToken, setPasswordResetToken] = useState("");
  const [passwordResetPassword, setPasswordResetPassword] = useState("");
  const [passwordResetConfirmation, setPasswordResetConfirmation] = useState("");
  const [passwordResetMessage, setPasswordResetMessage] = useState<string | null>(null);
  const [passwordResetBusy, setPasswordResetBusy] = useState(false);

  const [searchCoordinates, setSearchCoordinates] = useState<Coordinates | null>(null);
  const [devicePosition, setDevicePosition] = useState<DetectedDevicePosition | null>(null);
  const [locationLabel, setLocationLabel] = useState(t("home.locationCurrent"));
  const [locationSource, setLocationSource] = useState<LocationSource | null>(null);
  const locationSourceRef = useRef<LocationSource | null>(null);
  const [selectedLocationId, setSelectedLocationId] = useState<string | null>(null);
  const [locationPickerVisible, setLocationPickerVisible] = useState(false);
  const [locationResolving, setLocationResolving] = useState(false);
  const [locationIssue, setLocationIssue] = useState<LocationFailureReason | null>(null);
  const [locationCanOpenSettings, setLocationCanOpenSettings] = useState(false);
  const [locationPreferenceError, setLocationPreferenceError] = useState<string | null>(null);
  const [serviceAreas, setServiceAreas] = useState<ServiceArea[]>([]);
  const serviceAreasRef = useRef<ServiceArea[]>([]);
  const serviceAreasLoadSucceeded = useRef(false);
  const [serviceAreasLoading, setServiceAreasLoading] = useState(false);
  const [serviceAreasError, setServiceAreasError] = useState<string | null>(null);
  const locationRequestId = useRef(0);
  const appWasBackgrounded = useRef(false);
  const [clientVertical, setClientVertical] = useState<BusinessVertical>(DEFAULT_BUSINESS_VERTICAL);
  const [clientFilter, setClientFilter] = useState<DiscoverFilter>("nearby");
  const [homeSearch, setHomeSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [discoverError, setDiscoverError] = useState<string | null>(null);
  const [discoverErrorKind, setDiscoverErrorKind] = useState<DiscoverErrorKind>("request");
  const discoverRequestId = useRef(0);
  const [dishes, setDishes] = useState<DiscoverItem[]>([]);
  const [selectedDish, setSelectedDish] = useState<DiscoverItem | null>(null);
  const [quantity, setQuantity] = useState("1");
  const [cart, setCart] = useState<CartItem<DiscoverItem>[]>([]);
  const [pendingCartReplacement, setPendingCartReplacement] = useState<CartItem<DiscoverItem> | null>(null);
  const [checkoutLines, setCheckoutLines] = useState<CartItem<DiscoverItem>[]>([]);
  const [checkoutMerchantName, setCheckoutMerchantName] = useState<string | null>(null);
  const cartReturn = useRef<{ screen: Screen; dish: DiscoverItem | null }>({ screen: "discover", dish: null });
  const paymentLaunchLock = useRef(false);
  const paymentVerificationLock = useRef(false);
  const paymentVerificationRequested = useRef(false);
  const paymentRecoveryKey = useRef<string | null>(null);
  const returnedPayment = useRef<PaymentIdentity | null>(null);
  const recoveryTask = useRef<Promise<Payment | null> | null>(null);
  const activeCheckout = useRef<StoredPaymentSession | null>(null);
  const cartChanged = useRef(false);
  const currentCart = useRef(cart);
  currentCart.current = cart;
  const paymentSession = useRef(0);
  const appliedPayments = useRef(new Set<string>());
  const unopenedCheckout = useRef<{ id: string; url: string } | null>(null);
  const [reservationError, setReservationError] = useState<string | null>(null);
  const [payment, setPayment] = useState<Payment | null>(null);
  const [openingPayment, setOpeningPayment] = useState(false);
  const [paymentNetwork, setPaymentNetwork] = useState<"WAVE" | "ORANGEMONEY" | null>(null);
  const [paymentPhone, setPaymentPhone] = useState("");

  useEffect(() => {
    if (!me || (screen !== "cartSummary" && payment?.status !== "pending")) return;
    const subscription = AppState.addEventListener("change", (state) => {
      if (state === "active") void checkPayment();
    });
    return () => subscription.remove();
  }, [payment, me?.user.id, checkoutLines, screen]);

  function handleAppUrl(url: string | null) {
    if (!url) return;
    const parsed = ExpoLinking.parse(url);
    const resetToken = passwordResetTokenFromUrl(parsed);
    if (resetToken) {
      setPasswordResetToken(resetToken);
      setPasswordResetStep("confirm");
      setPasswordResetMessage(null);
      setAuthError(null);
      setPasswordResetPassword("");
      setPasswordResetConfirmation("");
      return;
    }
    const identity = paymentIdentityFromReturn(parsed);
    if (!identity) return;
    returnedPayment.current = identity;
    if (me) void checkPayment();
  }

  useEffect(() => {
    void ExpoLinking.getInitialURL().then(handleAppUrl);
    const subscription = Linking.addEventListener("url", ({ url }) => handleAppUrl(url));
    if (me) void checkPayment();
    return () => subscription.remove();
  }, [me?.user.id]);

  useEffect(() => {
    if (screen !== "cartSummary" || !checkoutLines.length) return;
    const key = checkoutPaymentKey(checkoutLines);
    if (paymentRecoveryKey.current === key) return;
    paymentRecoveryKey.current = key;
    void checkPayment();
  }, [screen, checkoutLines]);

  const [profile, setProfile] = useState<PublicCookProfile | null>(null);
  const [profileFavorite, setProfileFavorite] = useState(false);
  const [favorites, setFavorites] = useState<FavoriteCook[]>([]);
  const [ordersScope, setOrdersScope] = useState<"customer" | "cook">("customer");
  const [ordersRefresh, setOrdersRefresh] = useState(0);
  const [sectionLoading, setSectionLoading] = useState(false);
  const [sectionError, setSectionError] = useState<string | null>(null);
  const [reviewOrder, setReviewOrder] = useState<OrderHistory | null>(null);
  const [reviewRating, setReviewRating] = useState(0);
  const [reviewComment, setReviewComment] = useState("");
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [reviewResult, setReviewResult] = useState<{ orderId: string; id: string; rating: number; comment: string | null } | null>(null);
  const reviewLock = useRef(false);
  const [reviewBusy, setReviewBusy] = useState(false);
  useEffect(() => () => { menuRequest.current++; }, [screen, mode, me?.user.id, profile?.cook_id]);

  const [profileName, setProfileName] = useState("");
  const [profileBio, setProfileBio] = useState("");
  const [pickupLatitude, setPickupLatitude] = useState("");
  const [pickupLongitude, setPickupLongitude] = useState("");
  const [profilePhoto, setProfilePhoto] = useState<ImagePicker.ImagePickerAsset | null>(null);
  const [businessHours, setBusinessHours] = useState<BusinessHour[]>(Array.from({ length: 7 }, (_, weekday) => ({
    id: null, cook_profile_id: "", weekday, is_closed: true, opens_at: null, closes_at: null,
  })));
  const [hoursSaving, setHoursSaving] = useState(false);
  const [dishPhoto, setDishPhoto] = useState<ImagePicker.ImagePickerAsset | null>(null);
  const [dishName, setDishName] = useState("");
  const [description, setDescription] = useState("");
  const [price, setPrice] = useState("");
  const [availabilityDishId, setAvailabilityDishId] = useState<string | null>(null);
  const [availableDate, setAvailableDate] = useState(nextAvailabilityDate);
  const [startTime, setStartTime] = useState("11:00");
  const [endTime, setEndTime] = useState("14:00");
  const [portions, setPortions] = useState("8");
  const [cookDishes, setCookDishes] = useState<Dish[]>([]);
  const [cookAvailabilities, setCookAvailabilities] = useState<Availability[]>([]);
  const [cookLoading, setCookLoading] = useState(false);
  const [publishingDish, setPublishingDish] = useState(false);
  const [publishingAvailability, setPublishingAvailability] = useState(false);
  const publishingDishRef = useRef(false);
  const imagePickerOpen = useRef(false);
  const [cookError, setCookError] = useState<string | null>(null);
  const [cookMessage, setCookMessage] = useState<string | null>(null);

  async function resolveLocationLabel(next: Coordinates, requestId: number) {
    try {
      const [place] = await Location.reverseGeocodeAsync(next);
      const city = place?.city ?? place?.subregion ?? place?.region;
      const resolved = [city, place?.country].filter((value): value is string => Boolean(value)).join(", ");
      if (locationRequestId.current === requestId && resolved) {
        setLocationLabel(t("location.gpsPlaceLabel", { place: resolved }));
      }
    } catch {
      if (locationRequestId.current === requestId) setLocationLabel(t("location.currentGps"));
    }
  }

  async function loadServiceAreas(): Promise<ServiceArea[]> {
    setServiceAreasLoading(true);
    setServiceAreasError(null);
    try {
      const areas = (await getServiceAreas()).filter((area) => area.active);
      serviceAreasLoadSucceeded.current = true;
      serviceAreasRef.current = areas;
      setServiceAreas(areas);
      return areas;
    } catch {
      serviceAreasLoadSucceeded.current = false;
      setServiceAreasError(t("location.areasLoadFailed"));
      return serviceAreasRef.current;
    } finally {
      setServiceAreasLoading(false);
    }
  }

  function openLocationPicker() {
    setLocationPickerVisible(true);
    if (!serviceAreasRef.current.length && !serviceAreasLoading) void loadServiceAreas();
  }

  function logLocationResolution(
    source: LocationSource | null,
    permission: string,
    reason: string,
    details: {
      servicesEnabled?: boolean;
      accuracyMeters?: number | null;
      ageMs?: number | null;
      errorType?: string;
      errorCode?: string;
      positionMocked?: boolean;
    } = {},
  ) {
    if (!__DEV__) return;
    console.info("[LOCATION] resolved", {
      platform: Platform.OS,
      isPhysicalDevice: Device.isDevice,
      permission,
      source,
      reason,
      ...details,
    });
  }

  async function locate(options: {
    syncPickup?: boolean;
    forceGps?: boolean;
    serviceAreas?: ServiceArea[];
  } = {}): Promise<Coordinates | null> {
    const requestId = ++locationRequestId.current;
    const areas = options.serviceAreas ?? serviceAreasRef.current;
    setLocationResolving(true);
    let permissionStatus = "unknown";
    let servicesEnabled: boolean | undefined;
    let nativeErrorType: string | undefined;
    let nativeErrorCode: string | undefined;
    let gpsFix: { latitude: number; longitude: number; accuracy: number | null; timestamp: number; mocked?: boolean } | null = null;
    let failureReason: LocationFailureReason = "gps_unavailable";
    try {
      setLocationPreferenceError(null);
      if (!options.syncPickup && options.forceGps) {
        ++discoverRequestId.current;
        setLoading(false);
        setDishes([]);
        setDiscoverError(null);
        try {
          await clearManualLocationChoice(AsyncStorage);
        } catch {
          if (locationRequestId.current === requestId) {
            setLocationPreferenceError(t("location.preferenceSaveFailed"));
          }
          return null;
        }
        if (locationRequestId.current !== requestId) return null;
      }

      if (!options.syncPickup && !options.forceGps) {
        let restored: Awaited<ReturnType<typeof restoreManualLocationChoice>>;
        try {
          restored = await restoreManualLocationChoice(AsyncStorage, areas);
        } catch {
          if (locationRequestId.current === requestId) {
            setLocationPreferenceError(t("location.preferenceSaveFailed"));
          }
          return null;
        }
        const manualChoice = restored.choice;
        if (restored.hasStoredChoice && !manualChoice && serviceAreasLoadSucceeded.current) {
          try {
            await clearManualLocationChoice(AsyncStorage);
          } catch {
            if (locationRequestId.current === requestId) {
              setLocationPreferenceError(t("location.preferenceSaveFailed"));
            }
            return null;
          }
        }
        if (manualChoice) {
          const resolution = resolveLocation({ manualChoice, serviceAreas: areas });
          if (resolution.choice && locationRequestId.current === requestId) {
            setSearchCoordinates(resolution.choice);
            setLocationLabel(t("location.manualPlaceLabel", { place: resolution.choice.label }));
            setLocationSource(resolution.source);
            locationSourceRef.current = resolution.source;
            setSelectedLocationId(resolution.choice.id);
            setLocationIssue(null);
            setLocationCanOpenSettings(false);
            setDiscoverError(null);
            logLocationResolution(resolution.source, "manual_preference", resolution.reason);
            return resolution.choice;
          }
        }
      }

      // La position détectée et la zone de recherche sont deux états distincts.
      // Une tentative GPS en cours remplace l'ancien résultat seulement après résolution.
      setDevicePosition(null);

      let permission = await Location.getForegroundPermissionsAsync();
      if (shouldRequestForegroundPermission(permission)) {
        permission = await Location.requestForegroundPermissionsAsync();
      }
      permissionStatus = permission.status;

      failureReason = !permission.granted
        ? (permission.canAskAgain ? "permission_denied" : "permission_blocked")
        : "gps_unavailable";
      setLocationCanOpenSettings(!permission.granted && !permission.canAskAgain);
      if (permission.granted) {
        try {
          servicesEnabled = await Location.hasServicesEnabledAsync();
          if (!servicesEnabled) {
            failureReason = "services_disabled";
          } else {
            let timer: ReturnType<typeof setTimeout> | undefined;
            try {
              const current = await Promise.race([
                Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High }),
                new Promise<never>((_resolve, reject) => {
                  timer = setTimeout(() => reject(new Error("location_timeout")), 15_000);
                }),
              ]);
              gpsFix = {
                latitude: current.coords.latitude,
                longitude: current.coords.longitude,
                accuracy: current.coords.accuracy,
                timestamp: current.timestamp,
                mocked: current.mocked,
              };
            } catch (error) {
              const timedOut = error instanceof Error && error.message === "location_timeout";
              failureReason = timedOut ? "gps_timeout" : "gps_error";
              ({ errorType: nativeErrorType, errorCode: nativeErrorCode } = safeLocationErrorDetails(error));
            } finally {
              if (timer) clearTimeout(timer);
            }
          }
        } catch (error) {
          failureReason = "gps_error";
          ({ errorType: nativeErrorType, errorCode: nativeErrorCode } = safeLocationErrorDetails(error));
        }
      }

      const positionMocked = gpsFix?.mocked === true;
      const simulated = !Device.isDevice || positionMocked;
      if (simulated && !shouldAcceptSimulatedPosition(__DEV__)) {
        // Les positions d'émulateur/mock sont réservées aux diagnostics internes.
        gpsFix = null;
        failureReason = "gps_unavailable";
      }
      const resolution = resolveLocation({
        gpsFix,
        isSimulated: simulated,
        serviceAreas: areas,
        unavailableReason: failureReason,
      });
      if (locationRequestId.current !== requestId) return null;
      setDevicePosition(resolution.detectedPosition);
      if (options.syncPickup && resolution.source !== "gps") {
        setCookError(t("location.cookRequired"));
        logLocationResolution(null, permissionStatus, resolution.reason, {
          servicesEnabled,
          accuracyMeters: gpsFix?.accuracy,
          ageMs: gpsFix ? Date.now() - gpsFix.timestamp : null,
          errorType: nativeErrorType,
          errorCode: nativeErrorCode,
          positionMocked,
        });
        return null;
      }
      const chosen = resolution.choice;
      setSearchCoordinates(chosen ? { latitude: chosen.latitude, longitude: chosen.longitude } : null);
      setLocationSource(resolution.source);
      locationSourceRef.current = resolution.source;
      setSelectedLocationId(chosen?.id ?? null);
      const simulatedSource = resolution.source === "simulated"
        || resolution.detectedPosition?.source === "simulated";
      const locationLabelKey = simulatedSource
        ? (__DEV__ ? "location.simulated" : "location.detectedPositionLabel")
        : resolution.source === "gps" || resolution.detectedPosition?.source === "gps"
          ? "location.currentGpsLabel"
          : resolution.source === "manual" && chosen
            ? "location.manualPlaceLabel"
            : "location.unavailableLabel";
      setLocationLabel(locationLabelKey === "location.manualPlaceLabel" && chosen
        ? t(locationLabelKey, { place: chosen.label })
        : t(locationLabelKey));
      if (options.syncPickup && chosen) {
        setPickupLatitude(String(chosen.latitude));
        setPickupLongitude(String(chosen.longitude));
      }
      if (resolution.detectedPosition?.source === "gps") {
        void resolveLocationLabel(resolution.detectedPosition, requestId);
      }
      if (resolution.source) {
        setLocationIssue(null);
        setLocationCanOpenSettings(false);
        setDiscoverError(null);
        if (options.syncPickup) setCookError(null);
      } else {
        setLocationIssue(resolution.reason as LocationFailureReason);
        const messageKind = locationHomeMessageKind(resolution.reason);
        if (messageKind === "outside_service_area") {
          setDiscoverError(locationIssueMessage("outside_active_areas", areas));
          setDiscoverErrorKind("location");
        } else if (messageKind === "gps_unavailable") {
          setDiscoverError(t("location.noGps"));
          setDiscoverErrorKind("location");
        } else {
          setDiscoverError(null);
        }
      }
      logLocationResolution(resolution.source, permissionStatus, resolution.reason, {
        servicesEnabled,
        accuracyMeters: resolution.accuracyMeters,
        ageMs: gpsFix ? Date.now() - gpsFix.timestamp : null,
        errorType: nativeErrorType,
        errorCode: nativeErrorCode,
        positionMocked,
      });
      return chosen ? { latitude: chosen.latitude, longitude: chosen.longitude } : null;
    } catch (error) {
      if (locationRequestId.current !== requestId) return null;
      ({ errorType: nativeErrorType, errorCode: nativeErrorCode } = safeLocationErrorDetails(error));
      failureReason = "gps_error";
      if (options.syncPickup) {
        setCookError(t("location.cookRequired"));
        logLocationResolution(null, permissionStatus, "pickup_gps_error", {
          servicesEnabled,
          errorType: nativeErrorType,
          errorCode: nativeErrorCode,
        });
        return null;
      }
      const resolution = resolveLocation({
        serviceAreas: areas,
        unavailableReason: failureReason,
      });
      setDevicePosition(null);
      setSearchCoordinates(null);
      setLocationLabel(t("location.unavailableLabel"));
      setLocationSource(resolution.source);
      locationSourceRef.current = resolution.source;
      setSelectedLocationId(resolution.choice?.id ?? null);
      setLocationIssue(resolution.reason as LocationFailureReason);
      setLocationCanOpenSettings(false);
      if (resolution.source) setDiscoverError(null);
      else {
        setDiscoverError(t("location.noGps"));
        setDiscoverErrorKind("location");
      }
      logLocationResolution(null, permissionStatus, resolution.reason, {
        servicesEnabled,
        errorType: nativeErrorType,
        errorCode: nativeErrorCode,
        positionMocked: gpsFix?.mocked === true,
      });
      return null;
    } finally {
      if (locationRequestId.current === requestId) setLocationResolving(false);
    }
  }

  async function selectManualLocation(choice: LocationChoice) {
    const area = serviceAreasRef.current.find((candidate) => candidate.active && candidate.id === choice.id);
    if (!area) return;
    ++locationRequestId.current;
    const requestId = locationRequestId.current;
    setLocationResolving(false);
    const selected = parseLocationChoice(area);
    if (!selected) return;
    setLocationPreferenceError(null);
    try {
      await saveManualLocationChoice(AsyncStorage, selected);
    } catch {
      if (locationRequestId.current === requestId) {
        setLocationPreferenceError(t("location.preferenceSaveFailed"));
      }
      return;
    }
    if (locationRequestId.current !== requestId) return;
    setSearchCoordinates({ latitude: selected.latitude, longitude: selected.longitude });
    setLocationLabel(t("location.manualPlaceLabel", { place: selected.label }));
    setLocationSource("manual");
    locationSourceRef.current = "manual";
    setSelectedLocationId(selected.id);
    setLocationIssue(null);
    setLocationCanOpenSettings(false);
    setLocationPickerVisible(false);
    setDiscoverError(null);
    logLocationResolution("manual", "not_requested", "user_selected_zone");
    void refreshDiscover(selected, clientFilter, clientVertical, "manual");
  }

  useEffect(() => {
    const subscription = AppState.addEventListener("change", (state) => {
      if (state !== "active") {
        appWasBackgrounded.current = true;
        return;
      }
      // Les zones peuvent être administrées pendant que l'application est en arrière-plan.
      // Le serveur reste l'autorité; ceci actualise les choix affichés au retour.
      void loadServiceAreas();
      const previousSource = locationSource === "manual"
        ? "manual"
        : locationSource ?? devicePosition?.source ?? null;
      const shouldRefresh = shouldRefreshLocationAfterResume(appWasBackgrounded.current, previousSource);
      appWasBackgrounded.current = false;
      if (!shouldRefresh || !me || screen !== "discover") return;
      void locate({ forceGps: true, serviceAreas: serviceAreasRef.current }).then((next) => {
        if (next) void refreshDiscover(next, clientFilter, clientVertical, locationSourceRef.current);
        else setLocationPickerVisible(true);
      });
    });
    return () => subscription.remove();
  }, [me?.user.id, screen, locationSource, devicePosition?.timestamp, clientFilter, clientVertical]);

  async function useCurrentLocationForDiscovery() {
    setLocationPickerVisible(false);
    const next = await locate({ forceGps: true, serviceAreas: serviceAreasRef.current });
    if (next) void refreshDiscover(next, clientFilter, clientVertical, locationSourceRef.current);
    else setLocationPickerVisible(true);
  }

  async function refreshLocationAndDiscover() {
    if (locationSourceRef.current === "manual") {
      await refreshDiscover();
      return;
    }
    const next = await locate({ forceGps: true, serviceAreas: serviceAreasRef.current });
    if (next) void refreshDiscover(next, clientFilter, clientVertical, locationSourceRef.current);
    else setLocationPickerVisible(true);
  }

  async function refreshDiscover(
    next = searchCoordinates,
    filter = clientFilter,
    vertical = clientVertical,
    source = locationSourceRef.current,
  ) {
    if (!next) {
      setDiscoverError(t("location.noGps"));
      setDiscoverErrorKind("location");
      return;
    }
    const currentRequest = ++discoverRequestId.current;
    setLoading(true);
    setDiscoverError(null);
    try {
      const radiusKm = homeDiscoveryRadius(
        filter,
        ACTIVE_MARKET.nearbyRadiusKm,
        ACTIVE_MARKET.defaultRadiusKm,
      );
      if (__DEV__) {
        console.info("[LOCATION] discover", {
          platform: Platform.OS,
          source,
          filter,
          vertical,
        });
      }
      const results = await getDiscover({ ...next, radiusKm, filter, vertical });
      if (discoverRequestId.current !== currentRequest) return;
      setDishes(results);
    } catch (error) {
      if (discoverRequestId.current !== currentRequest) return;
      const kind: DiscoverErrorKind =
        error instanceof ApiError && error.status === 0
          ? "network"
          : error instanceof ApiError && error.status >= 500
            ? "server"
            : "request";
      setDiscoverErrorKind(kind);
      setDiscoverError(
        kind === "network"
          ? t("home.networkErrorBody")
          : kind === "server"
            ? t("home.serverErrorBody")
            : t("home.errorBody"),
      );
    } finally {
      if (discoverRequestId.current === currentRequest) setLoading(false);
    }
  }

  function selectDiscoveryFilter(filter: DiscoverFilter) {
    setClientFilter(filter);
    void refreshDiscover(searchCoordinates, filter, clientVertical);
  }

  function selectBusinessVertical(vertical: BusinessVertical) {
    if (vertical === clientVertical) return;
    setClientVertical(vertical);
    setDishes([]);
    setSelectedDish(null);
    void refreshDiscover(searchCoordinates, clientFilter, vertical);
  }

  function openExploreFarther() {
    setSelectedDish(null);
    setScreen("exploreFarther");
    requestAnimationFrame(() => {
      mainScrollRef.current?.scrollTo({ x: 0, y: 0, animated: false });
    });
  }

  async function loadCookContent(cookId = me?.cook_profile?.id) {
    if (!cookId) {
      setCookDishes([]);
      setCookAvailabilities([]);
      return;
    }
    setCookLoading(true);
    try {
      const [allDishes, allAvailabilities, hours] = await Promise.all([getDishes(), getAvailabilities(), getCookBusinessHours()]);
      const ownDishes = allDishes.filter((dish) => dish.cook_id === cookId);
      const ownDishIds = new Set(ownDishes.map((dish) => dish.id));
      setCookDishes(ownDishes);
      setCookAvailabilities(allAvailabilities.filter((availability) => ownDishIds.has(availability.dish_id)));
      setBusinessHours(hours);
    } catch (error) {
      setCookError(errorMessage(error));
    } finally {
      setCookLoading(false);
    }
  }

  async function expireSession() {
    setAccessToken(null);
    paymentSession.current += 1;
    setOpeningPayment(false);
    await deleteAccessToken().catch(() => undefined);
    setMe(null);
    setWelcomeDismissed(true);
    setRegistering(false);
    setAuthError(null);
    setSessionExpired(true);
  }

  async function hydrate(token: string, authStage?: "login" | "register") {
    setAccessToken(token);
    const profile = await getMe(authStage ? "hydration_me" : undefined);
    setMe(profile);
    if (authStage) logAuthDiagnostic("PROFILE_LOADED", authStage);
    void (async () => {
      const areas = await loadServiceAreas();
      const next = await locate({ serviceAreas: areas });
      if (next) void refreshDiscover(next);
      else setLocationPickerVisible(true);
    })();
  }

  useEffect(() => {
    let mounted = true;
    const timeout = setTimeout(() => {
      if (mounted) setRestoring(false);
    }, BOOTSTRAP_RESTORE_TIMEOUT_MS);
    void (async () => {
      try {
        const token = await getAccessToken();
        if (token) {
          await hydrate(token);
        }
      } catch (error) {
        setAccessToken(null);
        await deleteAccessToken();
        if (error instanceof ApiError && error.status === 401) {
          setWelcomeDismissed(true);
          setSessionExpired(true);
        }
      } finally {
        clearTimeout(timeout);
        if (mounted) setRestoring(false);
      }
    })();
    return () => {
      mounted = false;
      clearTimeout(timeout);
    };
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => setSplashMinimumElapsed(true), SPLASH_MINIMUM_VISIBLE_MS);
    return () => clearTimeout(timer);
  }, []);

  const splashShouldLeave = !restoring && splashMinimumElapsed;

  useEffect(() => {
    if (!splashVisible || !splashShouldLeave) return undefined;
    const fallback = setTimeout(() => setSplashVisible(false), 360);
    return () => clearTimeout(fallback);
  }, [splashShouldLeave, splashVisible]);

  useEffect(() => {
    if (splashVisible || !me || mode !== "client" || screen !== "discover" || selectedDish) return;
    const frame = requestAnimationFrame(() => {
      mainScrollRef.current?.scrollTo({ x: 0, y: 0, animated: false });
    });
    return () => cancelAnimationFrame(frame);
  }, [splashVisible, me?.user.id, mode, screen, selectedDish]);

  useEffect(() => {
    if (mode === "cook" && me?.cook_profile) void loadCookContent(me.cook_profile.id);
  }, [mode, me?.cook_profile?.id]);

  useEffect(() => {
    if (!me?.cook_profile) return;
    setProfileName(me.cook_profile.display_name);
    setProfileBio(me.cook_profile.bio ?? "");
    setPickupLatitude(String(me.cook_profile.latitude));
    setPickupLongitude(String(me.cook_profile.longitude));
  }, [me?.cook_profile?.id, me?.cook_profile?.latitude, me?.cook_profile?.longitude]);

  async function authenticate() {
    if (!email || !password || (registering && !firstName)) {
      setAuthError(t("form.required"));
      return;
    }
    setAuthError(null);
    try {
      const authStage = registering ? "register" : "login";
      const token = registering
        ? await register({ email, password, first_name: firstName, last_name: lastName || undefined })
        : await login({ email, password });
      logAuthDiagnostic("TOKEN_SAVE_START", authStage);
      await saveAccessToken(token.access_token);
      logAuthDiagnostic("TOKEN_SAVED", authStage);
      await hydrate(token.access_token, authStage);
      setSessionExpired(false);
    } catch (error) {
      setAuthError(error instanceof ApiError && error.status === 401
        ? t("auth.invalidCredentials") : errorMessage(error));
    }
  }

  async function probeApiHealth() {
    if (apiHealthProbeBusy) return;
    setApiHealthProbeBusy(true);
    setApiHealthProbeResult(null);
    try {
      await getApiHealth((status) => setApiHealthProbeResult({ kind: "http", status }));
    } catch (error) {
      if (error instanceof ApiError && error.status > 0) {
        setApiHealthProbeResult({
          kind: error.status >= 400 ? "http_error" : "response_error",
          status: error.status,
        });
      } else {
        setApiHealthProbeResult({
          kind: "network_error",
          errorType: error instanceof ApiError ? error.causeType ?? "Error" : "Error",
        });
      }
    } finally {
      setApiHealthProbeBusy(false);
    }
  }

  async function submitPasswordResetRequest() {
    if (!passwordResetEmail.trim()) {
      setAuthError(t("form.required"));
      return;
    }
    setAuthError(null);
    setPasswordResetBusy(true);
    try {
      await requestPasswordReset(passwordResetEmail.trim());
      setPasswordResetMessage(t("auth.resetRequestGeneric"));
    } catch (error) {
      setAuthError(errorMessage(error));
    } finally {
      setPasswordResetBusy(false);
    }
  }

  async function submitPasswordReset() {
    if (passwordResetPassword.length < 8) {
      setAuthError(t("auth.passwordTooShort"));
      return;
    }
    if (passwordResetPassword !== passwordResetConfirmation) {
      setAuthError(t("auth.passwordMismatch"));
      return;
    }
    setAuthError(null);
    setPasswordResetBusy(true);
    try {
      await confirmPasswordReset(passwordResetToken, passwordResetPassword);
      await deleteAccessToken().catch(() => undefined);
      setAccessToken(null);
      setMe(null);
      setPasswordResetStep("idle");
      setPasswordResetToken("");
      setPasswordResetPassword("");
      setPasswordResetConfirmation("");
      setRegistering(false);
      setEmail(passwordResetEmail);
      setPassword("");
      setPasswordResetMessage(t("auth.resetSuccess"));
    } catch (error) {
      setAuthError(error instanceof ApiError && error.status === 400
        ? t("auth.resetLinkInvalid") : errorMessage(error));
    } finally {
      setPasswordResetBusy(false);
    }
  }

  function returnToLogin() {
    setPasswordResetStep("idle");
    setPasswordResetToken("");
    setPasswordResetPassword("");
    setPasswordResetConfirmation("");
    setPasswordResetMessage(null);
    setAuthError(null);
  }

  async function logout() {
    await deleteAccessToken();
    setAccessToken(null);
    setMe(null);
    setSessionExpired(false);
    setDishes([]);
    setSelectedDish(null);
    setCart([]);
    setPendingCartReplacement(null);
    setCheckoutLines([]);
    setCheckoutMerchantName(null);
    setPayment(null);
    activeCheckout.current = null;
    returnedPayment.current = null;
    cartChanged.current = false;
    void clearCheckoutPayment();
    paymentSession.current += 1;
    unopenedCheckout.current = null;
    cartReturn.current = { screen: "discover", dish: null };
    setOpeningPayment(false);
    setMode("client");
    setScreen("discover");
  }

  function currentPickupCoordinates(): Coordinates | null {
    if (!pickupLatitude.trim() || !pickupLongitude.trim()) return null;
    const latitude = Number(pickupLatitude);
    const longitude = Number(pickupLongitude);
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude) || latitude < -90 || latitude > 90 || longitude < -180 || longitude > 180) {
      return null;
    }
    return { latitude, longitude };
  }

  async function proposeMerchantPickupFromDeviceGps() {
    setCookError(null);
    setCookMessage(null);
    try {
      let permission = await Location.getForegroundPermissionsAsync();
      if (shouldRequestForegroundPermission(permission)) {
        permission = await Location.requestForegroundPermissionsAsync();
      }
      if (!permission.granted) {
        setCookError(t(permission.canAskAgain ? "location.permissionDenied" : "location.permissionBlocked"));
        return;
      }
      if (!await Location.hasServicesEnabledAsync()) {
        setCookError(t("location.servicesDisabled"));
        return;
      }
      const current = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
      const validation = validateMerchantGpsFix({
        latitude: current.coords.latitude,
        longitude: current.coords.longitude,
        accuracy: current.coords.accuracy,
        timestamp: current.timestamp,
        mocked: current.mocked,
      }, { simulated: !Device.isDevice });
      if ("error" in validation) {
        const messageKey = validation.error === "simulated" ? "merchant.gpsSimulated"
          : validation.error === "stale" ? "location.stalePosition"
            : validation.error === "low_accuracy" ? "location.accuracyTooLow"
              : validation.error === "missing_accuracy" ? "location.accuracyUnavailable"
                : "location.invalidPosition";
        setCookError(t(messageKey));
        return;
      }

      const { latitude, longitude } = validation.coordinates;
      setPickupLatitude(String(latitude));
      setPickupLongitude(String(longitude));
      const assessment = assessMerchantServiceArea(validation.coordinates, serviceAreasRef.current);
      setCookMessage(assessment.status === "outside"
        ? t("merchant.gpsProposedOutsideArea")
        : t("merchant.gpsProposedReview"));
    } catch {
      setCookError(t("merchant.gpsUnavailable"));
    }
  }

  function isHeicOrHeif(asset: ImagePicker.ImagePickerAsset): boolean {
    const mimeType = asset.mimeType?.toLowerCase() ?? "";
    const fileName = asset.fileName?.toLowerCase() ?? "";
    const uri = asset.uri.toLowerCase();
    return mimeType.includes("heic") || mimeType.includes("heif")
      || fileName.endsWith(".heic") || fileName.endsWith(".heif")
      || uri.endsWith(".heic") || uri.endsWith(".heif");
  }

  function jpegFileName(asset: ImagePicker.ImagePickerAsset): string {
    const baseName = asset.fileName?.replace(/\.[^.]+$/, "") || `kwitli-photo-${Date.now()}`;
    return `${baseName}.jpg`;
  }

  function logMerchantImage(
    stage: "ORIGINAL" | "NORMALIZED",
    asset: ImagePicker.ImagePickerAsset,
    source: "camera" | "gallery",
    target: "article" | "establishment",
  ): void {
    if (!__DEV__) return;
    console.log(stage, {
      source,
      target,
      uri: asset.uri,
      filename: asset.fileName ?? null,
      mime: asset.mimeType ?? null,
    });
  }

  async function localImageSize(uri: string): Promise<number | null> {
    try {
      const response = await fetch(uri);
      const blob = await response.blob();
      return blob.size;
    } catch {
      return null;
    }
  }

  async function prepareMerchantImage(
    asset: ImagePicker.ImagePickerAsset,
    source: "camera" | "gallery",
    target: "article" | "establishment",
  ): Promise<ImagePicker.ImagePickerAsset | null> {
    logMerchantImage("ORIGINAL", asset, source, target);
    const originalWasHeic = isHeicOrHeif(asset);
    try {
      const actions: Parameters<typeof ImageManipulator.manipulateAsync>[1] = [];
      const largestSide = Math.max(asset.width, asset.height);
      if (largestSide > MAX_MERCHANT_PHOTO_DIMENSION) {
        actions.push(asset.width >= asset.height
          ? { resize: { width: MAX_MERCHANT_PHOTO_DIMENSION } }
          : { resize: { height: MAX_MERCHANT_PHOTO_DIMENSION } });
      }
      const converted = await ImageManipulator.manipulateAsync(asset.uri, actions, {
        compress: 0.8,
        format: ImageManipulator.SaveFormat.JPEG,
      });
      const optimizedSize = await localImageSize(converted.uri);
      const normalized = {
        ...asset,
        uri: converted.uri,
        width: converted.width,
        height: converted.height,
        fileName: jpegFileName(asset),
        mimeType: "image/jpeg",
      };
      if (__DEV__) {
        console.log("IMAGE ORIGINAL SIZE", {
          source,
          target,
          bytes: asset.fileSize ?? null,
          heicOrHeif: originalWasHeic,
        });
        console.log("IMAGE OPTIMIZED SIZE", { source, target, bytes: optimizedSize });
        console.log("IMAGE OPTIMIZED WIDTH/HEIGHT", {
          source,
          target,
          width: converted.width,
          height: converted.height,
        });
      }
      if (__DEV__) console.log("CONVERSION SUCCESS", { source, target, converted: true });
      logMerchantImage("NORMALIZED", normalized, source, target);
      return normalized;
    } catch (error) {
      if (__DEV__) console.warn("CONVERSION ERROR", {
        source, target,
        error: error instanceof Error ? error.message : String(error),
      });
      setCookError(t("error.imageConversion"));
      return null;
    }
  }

  async function pickMerchantImage(camera: boolean, target: "article" | "establishment"): Promise<ImagePicker.ImagePickerAsset | null> {
    if (imagePickerOpen.current) return null;
    imagePickerOpen.current = true;
    const source = camera ? "camera" : "gallery";
    setCookError(null);
    if (__DEV__) console.log("PHOTO FLOW START", { source, target });
    try {
      const permission = camera
        ? await ImagePicker.requestCameraPermissionsAsync()
        : await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!permission.granted) {
        setCookError(t("error.imagePermission"));
        return null;
      }
      const pickerOptions: ImagePicker.ImagePickerOptions = {
        mediaTypes: ["images"],
        allowsEditing: false,
        allowsMultipleSelection: false,
        quality: 0.8,
        preferredAssetRepresentationMode: ImagePicker.UIImagePickerPreferredAssetRepresentationMode.Compatible,
      };
      const result = camera
        ? await ImagePicker.launchCameraAsync(pickerOptions)
        : await ImagePicker.launchImageLibraryAsync(pickerOptions);
      if (result.canceled) {
        return null;
      }
      const asset = result.assets[0] ?? null;
      return asset ? await prepareMerchantImage(asset, source, target) : null;
    } finally {
      imagePickerOpen.current = false;
    }
  }

  async function choosePhoto(target: "dish" | "profile", camera: boolean) {
    const asset = await pickMerchantImage(camera, target === "profile" ? "establishment" : "article");
    if (!asset) return;
    if (target === "dish") setDishPhoto(asset);
    else setProfilePhoto(asset);
  }

  function openClientMode() {
    setMode("client");
    setScreen("discover");
    setProfile(null);
    setSelectedDish(null);
    detailProfileReturn.current = null;
    requestAnimationFrame(() => {
      mainScrollRef.current?.scrollTo({ x: 0, y: 0, animated: false });
    });
    void refreshDiscover();
  }

  function openCookMode() {
    if (me?.cook_profile) {
      setPickupLatitude(String(me.cook_profile.latitude));
      setPickupLongitude(String(me.cook_profile.longitude));
    }
    setMode("cook");
    setScreen("discover");
    setProfile(null);
    setSelectedDish(null);
  }

  function openDish(dish: DiscoverItem, returnProfile: PublicCookProfile | null = null) {
    setPendingCartReplacement(null);
    detailProfileReturn.current = returnProfile;
    setSelectedDish(dish);
    setQuantity("1");
    if (payment?.status !== "pending") setPayment(null);
    setReservationError(null);
    void (async () => {
      try {
        const favorite = await getFavoriteStatus(dish.cook_id);
        setProfileFavorite(favorite.is_favorite);
      } catch {
        setProfileFavorite(false);
      }
    })();
  }

  function addSelectedDishToCart(amount: number) {
    if (cartActionLock.current || !selectedDish || !canOrderQuantity(amount)) return;
    cartActionLock.current = true;
    requestAnimationFrame(() => { cartActionLock.current = false; });
    if (hasMixedCartCurrency(cart, selectedDish)) {
      Alert.alert(t("cart.title"), t("cart.mixedCurrency"));
      return;
    }
    if (requiresCartReplacement(cart, selectedDish)) {
      setPendingCartReplacement({ item: selectedDish, quantity: amount });
      return;
    }
    updateClientCart(addCartItem(currentCart.current, selectedDish, amount));
  }

  function replaceSelectedCart() {
    if (!pendingCartReplacement) return;
    const { item, quantity: amount } = pendingCartReplacement;
    if (!canOrderQuantity(amount)) return;
    updateClientCart(addCartItem([], item, amount));
    setPendingCartReplacement(null);
  }

  function continueShopping() {
    setSelectedDish(null);
    if (detailProfileReturn.current) {
      setProfile(detailProfileReturn.current);
      setScreen("cookProfile");
    } else {
      setScreen("discover");
    }
  }

  function closeDishDetail() {
    continueShopping();
  }

  function openCart() {
    if (screen === "cart") return;
    if (screen === "cartSummary") { setScreen("cart"); return; }
    cartReturn.current = { screen, dish: selectedDish };
    setSelectedDish(null);
    setScreen("cart");
  }

  function closeCart() {
    setScreen(cartReturn.current.screen);
    setSelectedDish(cartReturn.current.dish);
  }

  function updateClientCart(next: CartItem<DiscoverItem>[]) {
    if (!sameCart(next, currentCart.current)) {
      cartChanged.current = true;
      paymentSession.current += 1;
      activeCheckout.current = null;
      returnedPayment.current = null;
      paymentRecoveryKey.current = null;
      recoveryTask.current = null;
      unopenedCheckout.current = null;
      setPayment(null);
      setReservationError(null);
      setOpeningPayment(false);
      void clearCheckoutPayment().catch(() => undefined);
    }
    currentCart.current = next;
    setCart(next);
  }

  function continueCart() {
    if (paymentLaunchLock.current) return;
    const existing = activeCheckout.current;
    if (existing?.state === "active" && sameCart(existing.lines ?? [], cart)) {
      setScreen("cartSummary");
      return;
    }
    if (!cart.length || !me) return;
    paymentSession.current += 1;
    activeCheckout.current = newCheckoutSession(me.user.id, cart);
    returnedPayment.current = null;
    cartChanged.current = true;
    void saveCheckoutPayment(activeCheckout.current).catch(() => setReservationError(t("checkout.statusFailed")));
    setCheckoutLines(cart.map((line) => ({ ...line })));
    setCheckoutMerchantName(cart[0].item.cook_display_name);
    setPayment(null);
    paymentRecoveryKey.current = null;
    setReservationError(null);
    setScreen("cartSummary");
  }

  async function openProfile(cookId: string) {
    setSectionLoading(true);
    setSectionError(null);
    try {
      const [next, favorite] = await Promise.all([getPublicCook(cookId), getFavoriteStatus(cookId)]);
      setProfile(next);
      setProfileFavorite(favorite.is_favorite);
      setScreen("cookProfile");
    } catch (error) {
      setSectionError(errorMessage(error));
    } finally {
      setSectionLoading(false);
    }
  }

  async function openMenuArticle(dishId: string) {
    if (!profile) return;
    const article = menuArticle(profile, dishId);
    if (!article) { setSectionError(t("clientExperience.menuEmpty")); return; }
    openDish(article, profile);
    setScreen("discover");
  }

  async function toggleFavorite() {
    if (!profile) return;
    try {
      if (profileFavorite) await removeFavorite(profile.cook_id);
      else await addFavorite(profile.cook_id);
      setProfileFavorite(!profileFavorite);
    } catch (error) {
      setSectionError(error instanceof ApiError ? t("errors.favorites") : errorMessage(error));
    }
  }

  async function toggleSelectedCookFavorite() {
    if (!selectedDish) return;
    try {
      if (profileFavorite) await removeFavorite(selectedDish.cook_id);
      else await addFavorite(selectedDish.cook_id);
      setProfileFavorite(!profileFavorite);
    } catch (error) {
      setReservationError(error instanceof ApiError ? t("errors.favorites") : errorMessage(error));
    }
  }

  function selectClientTab(tab: ClientTab) {
    setSectionError(null);
    setProfile(null);
    setSelectedDish(null);
    if (tab === "home") {
      openClientMode();
    } else if (tab === "orders") {
      setMode("client");
      void loadOrders("customer");
    } else if (tab === "cook") {
      openCookMode();
    } else if (tab === "favorites") {
      void loadFavorites();
    } else {
      setMode("client");
      setScreen("account");
    }
  }

  async function loadFavorites() {
    setMode("client");
    setScreen("favorites");
    setSectionLoading(true);
    setSectionError(null);
    try {
      setFavorites(await getFavorites());
    } catch (error) {
      setSectionError(errorMessage(error));
    } finally {
      setSectionLoading(false);
    }
  }

  async function loadOrders(scope: "customer" | "cook") {
    setScreen("orders");
    setOrdersScope(scope);
    setOrdersRefresh((value) => value + 1);
    setSectionLoading(false);
    setSectionError(null);
    setReviewOrder(null);
    setReviewError(null);
    setReviewResult(null);
  }

  function applyPaymentStatus(updated: Payment) {
    if (appliedPayments.current.has(updated.id) && updated.status === "pending") return;
    const checkout = activeCheckout.current;
    if (!checkout || !paymentMatchesCheckout(checkout, updated)) return;
    setPayment(updated);
    if (!["declined", "error", "cancelled"].includes(updated.status)) {
      setReservationError(null);
    }
    if (updated.status === "approved" && !appliedPayments.current.has(updated.id)) {
      activeCheckout.current = { ...checkout, state: "completed", paymentId: undefined, txRef: undefined };
      returnedPayment.current = null;
      unopenedCheckout.current = null;
      void completeCheckoutPayment(checkout.sessionId).catch(() => undefined);
      appliedPayments.current.add(updated.id);
      setCart((current) => current.flatMap((line) => {
        const paidLine = updated.items?.find((entry) => entry.dish_id === line.item.dish_id
          || (entry.availability_id != null && entry.availability_id === line.item.availability_id));
        if (!paidLine) return [line];
        const remaining = line.quantity - paidLine.quantity;
        return remaining > 0 ? [{ ...line, quantity: remaining }] : [];
      }));
      void refreshDiscover();
    }
    if (["declined", "error", "cancelled"].includes(updated.status)) {
      setReservationError(t("checkout.paymentFailed"));
    }
  }

  async function verifyExistingPayment(target: Payment): Promise<Payment | null> {
    if (paymentVerificationLock.current) {
      paymentVerificationRequested.current = true;
      return null;
    }
    paymentVerificationLock.current = true;
    setOpeningPayment(true);
    const session = paymentSession.current;
    let updated: Payment | null = null;
    try {
      updated = await getPayment(target.id);
      if (session !== paymentSession.current) return null;
      applyPaymentStatus(updated);
      if (updated.status === "pending" && unopenedCheckout.current?.id === updated.id) {
        if (!await confirmPayTechTest(updated.provider) || session !== paymentSession.current) return updated;
        if (updated.provider === "flutterwave") openFlutterwavePage(unopenedCheckout.current.url);
        else await Linking.openURL(unopenedCheckout.current.url);
        unopenedCheckout.current = null;
      }
      return updated;
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        await expireSession();
        return null;
      }
      // Une erreur de lecture ne constitue jamais un refus fournisseur.
      if (session === paymentSession.current) {
        setPayment((current) => current?.id === target.id ? current : target);
        setReservationError(null);
      }
      return null;
    } finally {
      paymentVerificationLock.current = false;
      if (session === paymentSession.current) setOpeningPayment(false);
      if (paymentVerificationRequested.current && session === paymentSession.current) {
        paymentVerificationRequested.current = false;
        if ((updated ?? target).status === "pending") void verifyExistingPayment(updated ?? target);
      }
    }
  }

  async function recoverCheckoutPayment(): Promise<Payment | null> {
    if (!me) return null;
    if (recoveryTask.current) return recoveryTask.current;
    const session = paymentSession.current;
    const task = (async () => {
      const stored = await loadCheckoutPayment(me.user.id);
      if (session !== paymentSession.current || !stored) return null;
      let checkout = activeCheckout.current;
      if (!checkout) {
        // Reprise a froid uniquement avant toute creation/modification de panier.
        if (cartChanged.current || currentCart.current.length || checkoutLines.length) return null;
        checkout = stored;
        activeCheckout.current = stored;
      }
      if (!sameCheckout(stored, checkout)) return null;
      const updated = await readExistingPayment(stored, returnedPayment.current, getPayment, getPaymentByReference);
      if (!updated || session !== paymentSession.current) return null;
      if (!paymentMatchesCheckout(checkout, updated)) {
        paymentSession.current += 1;
        activeCheckout.current = null;
        returnedPayment.current = null;
        setPayment(null);
        setReservationError(null);
        void clearCheckoutPayment().catch(() => undefined);
        if (currentCart.current.length) {
          const fresh = newCheckoutSession(me.user.id, currentCart.current);
          activeCheckout.current = fresh;
          setCheckoutLines(fresh.lines!);
          setCheckoutMerchantName(fresh.merchantName ?? null);
          await saveCheckoutPayment(fresh);
        }
        return null;
      }
      const recovered = { ...stored, paymentId: updated.id, txRef: updated.provider_reference };
      await saveCheckoutPayment(recovered);
      if (session !== paymentSession.current) return null;
      activeCheckout.current = recovered;
      applyPaymentStatus(updated);
      if (!checkoutLines.length && stored?.lines?.length) setCheckoutLines(stored.lines);
      if (stored?.merchantName) setCheckoutMerchantName(stored.merchantName);
      setSelectedDish(null);
      setScreen("cartSummary");
      if (updated.order_id) {
        try {
          const order = await getOrder(updated.order_id);
          if (session === paymentSession.current) setCheckoutMerchantName(order.cook_display_name);
        } catch { /* Le statut confirme reste prioritaire si le nom ne peut pas etre relu. */ }
      }
      return updated;
    })();
    recoveryTask.current = task;
    try { return await task; } finally { if (recoveryTask.current === task) recoveryTask.current = null; }
  }

  async function checkPayment() {
    // Un etat React conserve par Fast Refresh ne constitue pas une liaison de checkout.
    if (!activeCheckout.current && currentCart.current.length) {
      setPayment(null);
      setReservationError(null);
      if (screen === "cartSummary") continueCart();
      return;
    }
    const session = paymentSession.current;
    setOpeningPayment(true);
    try { await recoverCheckoutPayment(); }
    catch (error) {
      if (error instanceof ApiError && error.status === 401) await expireSession();
      else if (session === paymentSession.current) setReservationError(t("checkout.statusFailed"));
    }
    finally { if (session === paymentSession.current) setOpeningPayment(false); }
  }

  function openFlutterwavePage(url: string) {
    const session = paymentSession.current;
    // Ne pas garder le verrou de creation pendant la session navigateur.
    void openFlutterwaveBrowser(url).then((returnedUrl) => {
      if (session !== paymentSession.current) return;
      if (returnedUrl) handleAppUrl(returnedUrl);
      else void checkPayment();
    }).catch(() => {
      if (session === paymentSession.current) void checkPayment();
    });
  }

  async function startPayment() {
    if (paymentLaunchLock.current) return;
    paymentLaunchLock.current = true;
    const session = paymentSession.current;
    let createdPayment: Payment | null = null;
    try {
      if (!payment?.id) setReservationError(null);
      const recovered = await recoverCheckoutPayment();
      if (session !== paymentSession.current) return;
      const terminalFailure = recovered && ["declined", "error", "failed", "cancelled"].includes(recovered.status);
      if (recovered && !terminalFailure) {
        if (recovered.status === "pending") {
          if (recovered.provider === "flutterwave" && recovered.next_action?.type === "external"
            && recovered.next_action.url) {
            openFlutterwavePage(recovered.next_action.url);
          } else if (recovered.provider !== "flutterwave") {
            const checkoutUrl = paymentCheckoutUrl(recovered);
            if (checkoutUrl && await confirmPayTechTest(recovered.provider)
              && session === paymentSession.current) await Linking.openURL(checkoutUrl);
          }
        }
        return;
      }
      if (!recovered && payment) return;
      if (!activeCheckout.current || activeCheckout.current.state !== "active"
        || activeCheckout.current.checkoutKey !== checkoutPaymentKey(checkoutLines)) return;
      if (!checkoutLines.length || checkoutLines.some((line) => !canOrderQuantity(line.quantity))) {
        setReservationError(t("checkout.quantityInvalid"));
        return;
      }
      if (checkoutLines.some((line) => !line.item.is_open)) {
        setReservationError(t("checkout.businessClosed"));
        return;
      }
      const mobileMoney = checkoutLines[0].item.currency === "XOF";
      if (mobileMoney && (!paymentNetwork || !/^\+?[0-9]{9,15}$/.test(paymentPhone.trim()))) {
        setReservationError(t("checkout.mobileMoneyRequired"));
        return;
      }
      setOpeningPayment(true);
      setReservationError(null);
      setPayment(null);
      if (terminalFailure) {
        const checkout = activeCheckout.current;
        if (!checkout) return;
        activeCheckout.current = {
          ...checkout,
          paymentAttempt: checkout.paymentAttempt + 1,
          paymentId: undefined,
          txRef: undefined,
        };
        await saveCheckoutPayment(activeCheckout.current);
      }
      if (__DEV__) {
        console.log("PAYMENT CREATE START", {
          amount: checkoutLines.reduce((sum, line) => sum + Number(line.item.price) * line.quantity, 0),
          currency: checkoutLines[0]?.item.currency ?? null,
          business_id: checkoutLines[0]?.item.cook_id ?? null,
        });
      }
      const checkout = activeCheckout.current;
      if (!checkout) return;
      const next = await createPayment({
        items: checkoutLines.map(({ item, quantity }) => ({ dish_id: item.dish_id, quantity })),
        ...(mobileMoney ? {
          network: paymentNetwork!,
          phone_number: paymentPhone.trim(),
          return_url: ExpoLinking.createURL("payment-return"),
        } : {}),
      }, paymentIdempotencyKey(checkout));
      createdPayment = next;
      if (__DEV__) {
        console.log("PAYMENT CREATE RESPONSE", {
          payment_id: next.id,
          tx_ref: next.provider_reference,
          provider: next.provider,
          action_type: next.next_action?.type ?? null,
          has_redirect: Boolean(next.next_action?.url || next.checkout_url),
        });
      }
      if (session !== paymentSession.current) return;
      setPayment(next);
      activeCheckout.current = { ...activeCheckout.current!, paymentId: next.id, txRef: next.provider_reference };
      await saveCheckoutPayment(activeCheckout.current);
      if (session !== paymentSession.current) return;
      if (next.status !== "pending") { applyPaymentStatus(next); return; }
      if (next.provider === "paydunya") {
        if (next.next_action?.type !== "wait") {
          if (!__DEV__) {
            // Paiement test PayDunya indisponible hors build de developpement : le dire au client.
            setReservationError(t("checkout.paymentFailed"));
            return;
          }
          const updated = await paySandboxInvoice(next.id);
          if (session !== paymentSession.current) return;
          applyPaymentStatus(updated);
          if (updated.status !== "pending") return;
        }
      } else if (next.provider === "flutterwave") {
        if (next.next_action?.type === "external" && next.next_action.url) {
          unopenedCheckout.current = { id: next.id, url: next.next_action.url };
          openFlutterwavePage(next.next_action.url);
          unopenedCheckout.current = null;
        }
      } else {
        const checkoutUrl = paymentCheckoutUrl(next);
        if (!checkoutUrl && next.next_action?.type !== "wait") throw new Error("PAYMENT_CHECKOUT_MISSING");
        if (checkoutUrl) {
          unopenedCheckout.current = { id: next.id, url: checkoutUrl };
          if (!await confirmPayTechTest(next.provider) || session !== paymentSession.current) return;
          await Linking.openURL(checkoutUrl);
          unopenedCheckout.current = null;
        }
      }
      // La création est terminée. Le retour et le polling vérifient désormais
      // le même Payment sans pouvoir en créer un second.
      paymentLaunchLock.current = false;
      if (session === paymentSession.current) setOpeningPayment(false);
      for (let attempt = 0; attempt < 6; attempt += 1) {
        await new Promise<void>((resolve) => setTimeout(resolve, 3000));
        if (session !== paymentSession.current) return;
        const updated = await verifyExistingPayment(next);
        if (updated && updated.status !== "pending") break;
      }
    } catch (error) {
      if (session !== paymentSession.current) return;
      if (error instanceof ApiError && error.status === 401) {
        await expireSession();
        return;
      }
      if (createdPayment) {
        const updated = await verifyExistingPayment(createdPayment);
        if (!updated || updated.status === "pending") return;
      } else {
        setReservationError(error instanceof ApiError && error.status === 409 && error.message.includes("fermé")
          ? t("checkout.businessClosed")
          : error instanceof ApiError && error.status === 409 ? t("error.stock") : t("checkout.paymentFailed"));
      }
    } finally {
      paymentLaunchLock.current = false;
      if (session === paymentSession.current) setOpeningPayment(false);
    }
  }

  async function submitReview(displayedOrderId?: string) {
    if (typeof __DEV__ !== "undefined" && __DEV__) console.log("REVIEW SUBMIT START", {
      order_id: reviewOrder?.id ?? null, displayed_order_id: displayedOrderId ?? null,
      rating: reviewRating, comment_present: reviewComment.trim().length > 0, comment_length: reviewComment.length,
    });
    if (!reviewOrder || reviewLock.current || reviewOrder.review_id ||
        (displayedOrderId && reviewOrder.id !== displayedOrderId) ||
        !["picked_up", "completed"].includes(reviewOrder.status) ||
        !Number.isInteger(reviewRating) || reviewRating < 1 || reviewRating > 5) return;
    reviewLock.current = true;
    setReviewBusy(true);
    setReviewError(null);
    try {
      const comment = reviewComment.trim().length > 0 ? reviewComment : undefined;
      if (typeof __DEV__ !== "undefined" && __DEV__) console.log("REVIEW REQUEST", { endpoint: "/api/v1/reviews", method: "POST" });
      const review = await createReview({ order_id: reviewOrder.id, rating: reviewRating, comment });
      if (typeof __DEV__ !== "undefined" && __DEV__) console.log("REVIEW SUBMIT SUCCESS", { order_id: reviewOrder.id, review_id: review.id });
      setReviewResult({ orderId: reviewOrder.id, id: review.id, rating: review.rating, comment: review.comment });
      setReviewOrder(null);
      setReviewRating(0);
      setReviewComment("");
    } catch (error) {
      if (typeof __DEV__ !== "undefined" && __DEV__) console.warn("REVIEW SUBMIT ERROR", {
        status: error instanceof ApiError ? error.status : 0,
        detail: error instanceof ApiError ? error.message : "UNKNOWN",
      });
      const detail = error instanceof ApiError ? error.message.toLocaleLowerCase() : "";
      setReviewError(error instanceof ApiError && error.status === 403
        ? detail.includes("noter cette commande")
          ? t("reviews.orderOwnershipError")
          : detail.includes("propre")
            ? t("reviews.ownOrderError")
            : t("reviews.submitError")
        : t("reviews.submitError"));
    } finally {
      reviewLock.current = false;
      setReviewBusy(false);
    }
  }

  async function createCookProfile() {
    const pickup = currentPickupCoordinates();
    if (!profileName || !pickup) {
      setCookError(t("location.cookRequired"));
      return;
    }
    try {
      let next = await createCook({ display_name: profileName, bio: profileBio || undefined, ...pickup });
      if (me) setMe({ ...me, cook_profile: next, user: { ...me.user, can_cook: true } });
      if (profilePhoto) {
        try {
          next = await uploadCookProfilePhoto(profilePhoto);
          if (me) setMe({ ...me, cook_profile: next, user: { ...me.user, can_cook: true } });
        } catch (error) {
          setCookError(merchantPhotoUploadErrorMessage(error));
        }
      }
      setProfilePhoto(null);
      setCookMessage(t("cook.profileCreated"));
      setMode("cook");
      setScreen("discover");
      await loadCookContent(next.id);
    } catch (error) {
      setCookError(errorMessage(error));
    }
  }

  async function savePickupPoint() {
    if (!me?.cook_profile) return;
    const pickup = currentPickupCoordinates();
    if (!pickup) {
      setCookError(t("location.cookRequired"));
      return;
    }
    try {
      const next = await updateCook(pickup);
      setMe({ ...me, cook_profile: next });
      setPickupLatitude(String(next.latitude));
      setPickupLongitude(String(next.longitude));
      setCookMessage(t("cook.pickupUpdated"));
    } catch (error) {
      setCookError(errorMessage(error));
    }
  }

  async function saveMerchantProfile() {
    if (!me?.cook_profile) return;
    const displayName = profileName.trim();
    if (displayName.length < 2) {
      setCookError(t("form.required"));
      return;
    }
    try {
      const next = await updateCook({ display_name: displayName, bio: profileBio.trim() || null });
      setMe({ ...me, cook_profile: next });
      setCookMessage(t("merchant.profileSaved"));
    } catch (error) {
      setCookError(errorMessage(error));
    }
  }

  function updateBusinessHour(
    weekday: number,
    values: Partial<Pick<BusinessHour, "is_closed" | "opens_at" | "closes_at">>,
  ) {
    setBusinessHours((current) => current.map((day) => day.weekday === weekday ? { ...day, ...values } : day));
  }

  async function saveMerchantBusinessHours() {
    const days = [...businessHours].sort((left, right) => left.weekday - right.weekday);
    const validTime = (value: string | null): value is string => value !== null && /^([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?$/.test(value);
    if (days.length !== 7 || days.some((day) => !day.is_closed
      && (!validTime(day.opens_at) || !validTime(day.closes_at) || day.opens_at >= day.closes_at))) {
      setCookError(t("merchant.hoursInvalid"));
      return;
    }
    setHoursSaving(true);
    try {
      const saved = await saveCookBusinessHours(days.map(({ weekday, is_closed, opens_at, closes_at }) => ({ weekday, is_closed, opens_at, closes_at })));
      setBusinessHours(saved);
      setCookError(null);
      setCookMessage(t("merchant.businessHoursSaved"));
      void refreshDiscover();
    } catch (error) {
      setCookError(errorMessage(error));
    } finally {
      setHoursSaving(false);
    }
  }

  async function replaceCookProfilePhoto(camera: boolean) {
    if (!me?.cook_profile) return;
    const asset = await pickMerchantImage(camera, "establishment");
    if (!asset) return;
    try {
      const next = await uploadCookProfilePhoto(asset);
      setMe({ ...me, cook_profile: next });
      setCookMessage(t("cook.photoUpdated"));
    } catch (error) {
      setCookError(merchantPhotoUploadErrorMessage(error));
    }
  }

  async function saveDishPhoto(dishId: string, asset: { uri: string; mimeType?: string | null; fileName?: string | null }) {
    try {
      await uploadDishPhoto(dishId, asset);
      setCookMessage(t("cook.photoUpdated"));
      await loadCookContent();
    } catch (error) {
      setCookError(merchantPhotoUploadErrorMessage(error));
      throw error;
    }
  }

  async function updateMerchantArticle(
    dishId: string,
    payload: { name?: string; description?: string; price?: string; category?: string | null; is_active?: boolean },
  ) {
    try {
      setCookError(null);
      setCookMessage(null);
      await updateDish(dishId, payload);
      setCookMessage(t("merchant.articleUpdated"));
      await loadCookContent();
    } catch (error) {
      setCookError(errorMessage(error));
      throw error;
    }
  }

  async function updateMerchantAvailability(
    availabilityId: string,
    payload: { available_date?: string; start_time?: string; end_time?: string; total_portions?: number; remaining_portions?: number; status?: "active" | "inactive" },
  ) {
    try {
      setCookError(null);
      setCookMessage(null);
      await updateAvailability(availabilityId, payload);
      setCookMessage(t("merchant.availabilityUpdated"));
      await loadCookContent();
    } catch (error) {
      setCookError(errorMessage(error));
      throw error;
    }
  }

  async function publishDish(options: { category: string | null; is_active: boolean }) {
    if (publishingDishRef.current) return false;
    if (!me?.cook_profile) {
      setCookError(t("error.cook"));
      return false;
    }
    // Accepter « 1 500 » et « 1500,50 » comme on les tape en francais.
    const numericPrice = Number(price.replace(/[\s  ]/g, "").replace(",", "."));
    if (!dishName.trim() || !description.trim()) {
      setCookError(t("form.required"));
      return false;
    }
    if (!Number.isFinite(numericPrice) || numericPrice <= 0) {
      setCookError(t("cook.invalidPrice"));
      return false;
    }
    publishingDishRef.current = true;
    setPublishingDish(true);
    setCookError(null);
    setCookMessage(null);
    try {
      const article = await createDish({
        name: dishName.trim(),
        description: description.trim(),
        price: String(numericPrice),
        currency: ACTIVE_MARKET.currency,
        category: options.category,
        is_active: options.is_active,
      });
      let photoUploadFailed = false;
      if (dishPhoto) {
        try {
          await uploadDishPhoto(article.id, dishPhoto);
        } catch (error) {
          photoUploadFailed = true;
          setCookError(merchantPhotoUploadErrorMessage(error));
        }
      }
      setAvailabilityDishId(null);
      setDishName("");
      setDescription("");
      setPrice("");
      setDishPhoto(null);
      setCookMessage(photoUploadFailed ? null : t("cook.dishPublished"));
      await loadCookContent();
      return true;
    } catch (error) {
      setCookError(error instanceof ApiError ? errorMessage(error) : t("cook.dishCreationFailed"));
      return false;
    } finally {
      publishingDishRef.current = false;
      setPublishingDish(false);
    }
  }

  function cancelNewArticle() {
    setDishName("");
    setDescription("");
    setPrice("");
    setDishPhoto(null);
  }

  function selectAvailabilityArticle(articleId: string | null) {
    if (articleId) {
      setAvailableDate(nextAvailabilityDate());
      setStartTime("11:00");
      setEndTime("14:00");
      setPortions("8");
    }
    setAvailabilityDishId(articleId);
  }

  async function publishAvailability(status: "active" | "inactive") {
    if (publishingAvailability) return;
    const totalPortions = Number(portions);
    if (!availabilityDishId || !availableDate || !startTime || !endTime || !Number.isInteger(totalPortions) || totalPortions < 1) {
      setCookError(t("form.required"));
      return;
    }
    setPublishingAvailability(true);
    setCookError(null);
    try {
      await createAvailability({
        dish_id: availabilityDishId,
        available_date: availableDate,
        start_time: startTime,
        end_time: endTime,
        total_portions: totalPortions,
        status,
      });
      setAvailabilityDishId(null);
      setCookMessage(t("cook.availabilityCreated"));
      await loadCookContent();
    } catch (error) {
      setCookError(errorMessage(error));
    } finally {
      setPublishingAvailability(false);
    }
  }

  if (splashVisible) {
    return (
      <BrandSplash
        leaving={splashShouldLeave}
        onHidden={() => setSplashVisible(false)}
      />
    );
  }

  if (!me || passwordResetStep !== "idle") {
    if (!welcomeDismissed && passwordResetStep === "idle") return <SafeAreaView style={styles.screen}>
      <ScrollView contentContainerStyle={styles.content}>
        <ClientWelcome onContinue={() => setWelcomeDismissed(true)} />
      </ScrollView>
    </SafeAreaView>;
    return (
      <SafeAreaView style={styles.screen}>
        <ScrollView contentContainerStyle={styles.content}>
          <Text style={styles.title}>{passwordResetStep === "request" ? t("auth.resetRequestTitle") : passwordResetStep === "confirm" ? t("auth.resetConfirmTitle") : t("auth.welcome")}</Text>
          {passwordResetStep === "idle" ? <>
            {registering && <><Input label={t("auth.firstName")} value={firstName} onChangeText={setFirstName} /><Input label={t("auth.lastName")} value={lastName} onChangeText={setLastName} /></>}
            <Input label={t("auth.email")} value={email} onChangeText={setEmail} />
            <Input label={t("auth.password")} value={password} onChangeText={setPassword} secure />
            {sessionExpired && !authError && <Text style={styles.error}>{t("error.auth")}</Text>}
            {passwordResetMessage && <Text>{passwordResetMessage}</Text>}
            {authError && <Text style={styles.error}>{authError}</Text>}
            <Pressable style={styles.primary} onPress={() => { setPasswordResetMessage(null); void authenticate(); }}><Text style={styles.primaryText}>{sessionExpired ? t("auth.reconnect") : registering ? t("auth.register") : t("auth.login")}</Text></Pressable>
            {__DEV__ && <>
              <Pressable disabled={apiHealthProbeBusy} onPress={() => void probeApiHealth()}><Text>{t(apiHealthProbeBusy ? "debug.apiHealthChecking" : "debug.apiHealthCheck")}</Text></Pressable>
              <Text>{t("debug.apiHealthTarget", { url: API_URL ? `${API_URL}/api/v1/health` : t("debug.apiHealthUnconfigured") })}</Text>
              {apiHealthProbeBusy && <Text>{t("debug.apiHealthInProgress")}</Text>}
              {apiHealthProbeResult?.kind === "http" && <Text>{t("debug.apiHealthHttp", { status: apiHealthProbeResult.status })}</Text>}
              {apiHealthProbeResult?.kind === "http_error" && <Text>{t("debug.apiHealthHttpError", { status: apiHealthProbeResult.status })}</Text>}
              {apiHealthProbeResult?.kind === "response_error" && <Text>{t("debug.apiHealthResponseError", { status: apiHealthProbeResult.status })}</Text>}
              {apiHealthProbeResult?.kind === "network_error" && <Text>{t("debug.apiHealthNetworkError", { errorType: apiHealthProbeResult.errorType })}</Text>}
            </>}
            {!registering && <Pressable onPress={() => { setPasswordResetEmail(email); setPasswordResetMessage(null); setAuthError(null); setPasswordResetStep("request"); }}><Text>{t("auth.forgotPassword")}</Text></Pressable>}
            {!sessionExpired && <Pressable onPress={() => setRegistering(!registering)}><Text>{registering ? t("auth.switchToLogin") : t("auth.switchToRegister")}</Text></Pressable>}
          </> : passwordResetStep === "request" ? <>
            <Input label={t("auth.email")} value={passwordResetEmail} onChangeText={setPasswordResetEmail} />
            {passwordResetMessage && <Text>{passwordResetMessage}</Text>}
            {authError && <Text style={styles.error}>{authError}</Text>}
            <Pressable style={styles.primary} disabled={passwordResetBusy} onPress={() => void submitPasswordResetRequest()}><Text style={styles.primaryText}>{passwordResetBusy ? t("auth.loading") : t("auth.sendResetLink")}</Text></Pressable>
            <Pressable onPress={returnToLogin}><Text>{t("auth.backToLogin")}</Text></Pressable>
          </> : <>
            <Input label={t("auth.newPassword")} value={passwordResetPassword} onChangeText={setPasswordResetPassword} secure />
            <Input label={t("auth.confirmPassword")} value={passwordResetConfirmation} onChangeText={setPasswordResetConfirmation} secure />
            {authError && <Text style={styles.error}>{authError}</Text>}
            <Pressable style={styles.primary} disabled={passwordResetBusy || !passwordResetToken} onPress={() => void submitPasswordReset()}><Text style={styles.primaryText}>{passwordResetBusy ? t("auth.loading") : t("auth.resetPassword")}</Text></Pressable>
            <Pressable onPress={returnToLogin}><Text>{t("auth.backToLogin")}</Text></Pressable>
          </>}
        </ScrollView>
      </SafeAreaView>
    );
  }

  const hasCook = me.cook_profile !== null;
  const selectedCookDish = availabilityDishId ? cookDishes.find((dish) => dish.id === availabilityDishId) : null;

  const modeSwitch = (
    <View style={styles.modeSwitch} accessibilityLabel={t("mode.switch")}>
      <Pressable accessibilityRole="button" style={[styles.modeButton, mode === "client" && styles.modeButtonActive]} onPress={openClientMode}>
        <Text style={[styles.modeText, mode === "client" && styles.modeTextActive]}>{t("mode.client")}</Text>
      </Pressable>
      <Pressable accessibilityRole="button" style={[styles.modeButton, mode === "cook" && styles.modeButtonActive]} onPress={openCookMode}>
        <Text style={[styles.modeText, mode === "cook" && styles.modeTextActive]}>{t("mode.cook")}</Text>
      </Pressable>
    </View>
  );

  const profileView = profile && (mode === "client" ? <PublicBusinessProfile profile={profile}
    favorite={profileFavorite} onFavorite={() => void toggleFavorite()} busy={sectionLoading}
    onOpen={(id) => void openMenuArticle(id)}
    onBack={() => { menuRequest.current++; setSectionLoading(false); setScreen("discover"); }} /> : (
    <View style={styles.card}>
      <Photo uri={profile.profile_photo_url} large />
      <Text style={styles.title}>{profile.display_name}</Text>
      {profile.is_verified && <Text>{t("cookProfile.verified")}</Text>}
      <Text>{profile.rating_average ? `${profile.rating_average} - ${profile.rating_count} ${t("cookProfile.reviews")}` : t("cookProfile.new")}</Text>
      <Text>{profile.orders_completed} {t("cookProfile.completedOrders")}</Text>
      {profile.bio && <Text>{profile.bio}</Text>}
      <Pressable style={styles.primary} onPress={() => void toggleFavorite()}><Text style={styles.primaryText}>{profileFavorite ? t("favorites.remove") : t("favorites.add")}</Text></Pressable>
      <Text style={styles.subtitle}>{t("cookProfile.availableDishes")}</Text>
      {profile.available_dishes.map((dish) => <View key={dish.dish_id}><Text>{dish.name} - {money(dish.price, dish.currency)}</Text></View>)}
      <Text style={styles.subtitle}>{t("cookProfile.recentReviews")}</Text>
      {profile.recent_reviews.length === 0 ? <Text>{t("cookProfile.noReviews")}</Text> : profile.recent_reviews.map((review) => <View key={review.id}><Text>{review.rating}/5</Text>{review.comment && <Text>{review.comment}</Text>}</View>)}
      <Pressable onPress={() => setScreen("discover")}><Text>{t("common.back")}</Text></Pressable>
    </View>
  ));

  const orderView = (
    <View>
      <OrdersScreen key={ordersScope} scope={ordersScope} refreshKey={ordersRefresh} currentUserId={me?.user.id ?? null} onReview={(order, rating = 0) => {
        if (order.review_id || !["picked_up", "completed"].includes(order.status)) return;
        setReviewRating(rating);
        setReviewComment("");
        setReviewError(null);
        setSectionError(null);
        setReviewOrder(order);
      }} renderReview={(order) => reviewOrder?.id === order.id && <ClientReviewForm rating={reviewRating} comment={reviewComment}
        busy={reviewBusy} error={reviewError} onRating={setReviewRating} onComment={setReviewComment}
        onSubmit={() => void submitReview(order.id)} onCancel={() => { setReviewOrder(null); setReviewRating(0); setReviewComment(""); setReviewError(null); }} />}
        reviewResult={reviewResult} />
      {reviewOrder && ordersScope === "cook" && <View style={styles.card}><Text style={styles.subtitle}>{t("reviews.title")}</Text><Text>{t("reviews.rating")}</Text><View style={styles.navigation}>{[1, 2, 3, 4, 5].map((rating) => <Pressable key={rating} onPress={() => setReviewRating(rating)}><Text>{rating === reviewRating ? `[${rating}]` : String(rating)}</Text></Pressable>)}</View><Input label={t("reviews.comment")} value={reviewComment} onChangeText={setReviewComment} /><Pressable style={styles.primary} onPress={() => void submitReview()}><Text style={styles.primaryText}>{t("reviews.send")}</Text></Pressable></View>}
    </View>
  );

  // Recherche locale : nom du plat ou du commerce, sans tenir compte des accents.
  const normalizeSearch = (value: string) => value.normalize("NFD").replace(/[̀-ͯ]/g, "").toLocaleLowerCase().trim();
  const searchQuery = normalizeSearch(homeSearch);
  const visibleDishes = searchQuery
    ? dishes.filter((item) => normalizeSearch(`${item.dish_name} ${item.cook_display_name}`).includes(searchQuery))
    : dishes;
  const filterEmptyMessage = clientFilter === "fresh"
    ? t("home.filterEmpty.fresh")
    : t("home.filterEmpty.new");
  const compactHome = viewportWidth < breakpoints.compactPhone;
  const discoverErrorPresentation = discoverErrorKind === "network"
    ? { title: t("home.networkErrorTitle"), body: t("home.networkErrorBody"), icon: "wifi-outline" as const }
    : discoverErrorKind === "server"
      ? { title: t("home.serverErrorTitle"), body: t("home.serverErrorBody"), icon: "cloud-offline-outline" as const }
      : discoverErrorKind === "location"
        ? { title: t("home.locationErrorTitle"), body: t("home.locationErrorBody"), icon: "location-outline" as const }
        : { title: t("home.errorTitle"), body: t("home.errorBody"), icon: "alert-circle-outline" as const };
  const initialHomeLoading = loading && dishes.length === 0;
  const populatedClientView = (
    <View style={styles.clientHome}>
      <AppHeader
        firstName={me.user.first_name}
        locationLabel={locationLabel}
        locationIsManual={locationSource === "manual"}
        onLocationPress={openLocationPicker}
        onProfilePress={() => selectClientTab("profile")}
      />

      <Text accessibilityRole="header" maxFontSizeMultiplier={1.15} style={[styles.heroTitle, compactHome && styles.heroTitleCompact]}>
        {t("home.headline")}
      </Text>

      <View style={styles.searchBar}>
        <Ionicons color={colors.ink} name="search" size={20} />
        <TextInput
          accessibilityLabel={t("home.searchLabel")}
          autoCorrect={false}
          clearButtonMode="never"
          onChangeText={setHomeSearch}
          placeholder={t("home.searchPlaceholder")}
          placeholderTextColor={colors.cocoaMuted}
          returnKeyType="search"
          style={styles.searchInput}
          value={homeSearch}
        />
        {!!homeSearch && <Pressable accessibilityLabel={t("home.searchClear")} accessibilityRole="button" hitSlop={8}
          onPress={() => setHomeSearch("")} style={({ pressed }) => [styles.searchClear, pressed && styles.pressed]}>
          <Ionicons color={colors.cocoaMuted} name="close-circle" size={20} />
        </Pressable>}
      </View>

      {VISIBLE_CLIENT_VERTICALS.length > 1 && <View style={styles.verticalSelector}>
        {VISIBLE_CLIENT_VERTICALS.map((vertical) => (
          <FilterChip
            key={vertical}
            label={t(VERTICAL_LABELS[vertical])}
            onPress={() => selectBusinessVertical(vertical)}
            selected={clientVertical === vertical}
          />
        ))}
      </View>}

      <ScrollView
        alwaysBounceHorizontal={false}
        bounces={false}
        contentContainerStyle={styles.filters}
        directionalLockEnabled
        horizontal
        overScrollMode="never"
        showsHorizontalScrollIndicator={false}
        style={styles.filterScroll}
      >
        <FilterChip icon="restaurant-outline" label={t("home.filter.nearby")} onPress={() => selectDiscoveryFilter("nearby")} selected={clientFilter === "nearby"} />
        <FilterChip icon="flame-outline" label={t("home.filter.fresh")} onPress={() => selectDiscoveryFilter("fresh")} selected={clientFilter === "fresh"} />
        <FilterChip icon="sparkles-outline" label={t("home.filter.new")} onPress={() => selectDiscoveryFilter("new")} selected={clientFilter === "new"} />
      </ScrollView>

      <View style={styles.sectionHeading}>
        <Text style={styles.homeSectionTitle}>{t("home.sectionTitle")}</Text>
        <Pressable
          accessibilityLabel={t("client.refresh")}
          accessibilityRole="button"
          onPress={() => void refreshLocationAndDiscover()}
          style={({ pressed }) => [styles.refreshButton, pressed && styles.pressed]}
        >
          <Ionicons color={colors.brandGreen} name="refresh" size={20} />
        </Pressable>
      </View>

      <ScrollView
        alwaysBounceVertical={false}
        automaticallyAdjustContentInsets={false}
        bounces={false}
        contentInsetAdjustmentBehavior="never"
        contentContainerStyle={styles.dishResultsContent}
        overScrollMode="never"
        showsVerticalScrollIndicator={false}
        style={styles.dishResultsScroll}
      >
        {!loading && discoverError && (
          <HomeState
            actionLabel={t("home.retry")}
            body={discoverErrorPresentation.body}
            icon={discoverErrorPresentation.icon}
            onAction={() => void (discoverErrorKind === "location"
              ? useCurrentLocationForDiscovery()
              : refreshDiscover())}
            onSecondaryAction={discoverErrorKind === "location" ? openLocationPicker : undefined}
            secondaryActionLabel={discoverErrorKind === "location" ? t("location.changeZone") : undefined}
            title={discoverErrorPresentation.title}
            tone="error"
          />
        )}

        {!loading && !discoverError && searchCoordinates && shouldShowHomeCauldron(clientFilter, dishes.length) && (
          <HomeState
            actionIcon="navigate-outline"
            actionLabel={t("home.expandSearch")}
            body={t("home.emptyBody")}
            icon="restaurant-outline"
            onAction={openExploreFarther}
            onSecondaryAction={() => void refreshLocationAndDiscover()}
            secondaryActionLabel={t("home.retry")}
            title={t(VERTICAL_EMPTY_TITLES[clientVertical])}
            variant="empty"
          />
        )}

        {!loading && !discoverError && searchCoordinates && clientFilter !== "nearby" && dishes.length === 0 && (
          <View style={styles.filterEmpty}>
            <Ionicons color={colors.brandGreen} name="time-outline" size={20} />
            <Text style={styles.filterEmptyText}>{filterEmptyMessage}</Text>
          </View>
        )}

        {!loading && !discoverError && !!searchQuery && dishes.length > 0 && visibleDishes.length === 0 && (
          <View style={styles.filterEmpty}>
            <Ionicons color={colors.ink} name="search-outline" size={20} />
            <Text style={styles.filterEmptyText}>{t("home.searchEmpty", { query: homeSearch.trim() })}</Text>
          </View>
        )}

        <View style={styles.dishList}>
          {groupDiscoverItemsByBusiness(visibleDishes).map((items) => (
            <BusinessDiscoveryCard key={items[0].cook_id} items={items} onPress={() => void openProfile(items[0].cook_id)} />
          ))}
        </View>
      </ScrollView>
    </View>
  );
  const clientView = initialHomeLoading
    ? <HomeSkeleton accessibilityLabel={`${t("home.loadingTitle")}. ${t("home.loadingBody")}`} />
    : populatedClientView;
  const merchantPickupArea = assessMerchantServiceArea(currentPickupCoordinates(), serviceAreas);

  const cookView = (
    <View style={styles.page}>
      {cookError && <Text style={styles.error}>{cookError}</Text>}
      {cookMessage && <Text style={styles.success}>{cookMessage}</Text>}
      <MerchantDashboard
        articles={cookDishes}
        articleDescription={description}
        articleName={dishName}
        articlePhoto={dishPhoto}
        articlePrice={price}
        availabilities={cookAvailabilities}
        availabilityDate={availableDate}
        currency={ACTIVE_MARKET.currency}
        businessHours={businessHours}
        hoursSaving={hoursSaving}
        endTime={endTime}
        loading={cookLoading}
        onArticleDescriptionChange={setDescription}
        onArticleNameChange={setDishName}
        onArticlePriceChange={setPrice}
        onAvailabilityDateChange={setAvailableDate}
        onCreateProfile={() => void createCookProfile()}
        onSaveProfile={() => void saveMerchantProfile()}
        onBusinessHourChange={updateBusinessHour}
        onSaveBusinessHours={() => void saveMerchantBusinessHours()}
        onEndTimeChange={setEndTime}
        onPickArticlePhoto={(camera) => void choosePhoto("dish", camera)}
        onPickProfilePhoto={(camera) => void choosePhoto("profile", camera)}
        onPickupLatitudeChange={setPickupLatitude}
        onPickupLongitudeChange={setPickupLongitude}
        onProfileBioChange={setProfileBio}
        onProfileNameChange={setProfileName}
        onPublishArticle={publishDish}
        onCancelNewArticle={cancelNewArticle}
        onPublishAvailability={(status) => void publishAvailability(status)}
        onPickEditArticlePhoto={(camera) => pickMerchantImage(camera, "article")}
        onSaveEditArticlePhoto={saveDishPhoto}
        onReplaceProfilePhoto={(camera) => void replaceCookProfilePhoto(camera)}
        onSavePickup={() => void savePickupPoint()}
        onSelectAvailabilityArticle={selectAvailabilityArticle}
        onStartTimeChange={setStartTime}
        onStockQuantityChange={setPortions}
        onUpdateArticle={updateMerchantArticle}
        onUpdateAvailability={updateMerchantAvailability}
        onUseCurrentLocation={() => void proposeMerchantPickupFromDeviceGps()}
        pickupLatitude={pickupLatitude}
        pickupLongitude={pickupLongitude}
        pickupAreaStatus={merchantPickupArea.status}
        pickupAreaLabel={merchantPickupArea.areaLabel}
        profile={me.cook_profile}
        profileBio={profileBio}
        profileName={profileName}
        profilePhoto={profilePhoto}
        publishingArticle={publishingDish}
        publishingAvailability={publishingAvailability}
        selectedAvailabilityArticle={selectedCookDish ?? null}
        startTime={startTime}
        stockQuantity={portions}
      />
    </View>
  );

  const favoritesView = (
    <View style={styles.page}>
      <Text style={styles.title}>{t("favorites.title")}</Text>
      {favorites.length === 0 && <Text style={styles.bodyText}>{t("favorites.empty")}</Text>}
      {favorites.map((favorite) => (
        <Pressable
          key={favorite.id}
          accessibilityRole="button"
          style={({ pressed }) => [styles.card, pressed && styles.pressed]}
          onPress={() => void openProfile(favorite.cook_id)}
        >
          <Photo uri={favorite.profile_photo_url} client />
          <Text style={styles.cardTitle}>{favorite.display_name}</Text>
          <Text style={styles.bodyText}>{favorite.rating_average ?? t("cookProfile.new")}</Text>
          <Text style={styles.bodyText}>{favorite.has_active_availability ? t("favorites.available") : t("favorites.unavailable")}</Text>
        </Pressable>
      ))}
    </View>
  );

  const accountView = mode === "client" ? <ClientProfile
    firstName={me.user.first_name}
    lastName={me.user.last_name}
    email={me.user.email}
    onPrivacy={() => Alert.alert(t("clientProfile.privacy"), t("clientProfile.privacyBody"))}
    onLogout={() => void logout()}
  /> : (
    <View style={styles.page}>
      <Text style={styles.title}>{t("profile.title")}</Text>
      <View style={styles.accountCard}>
        <View style={styles.accountAvatar}>
          <Text style={styles.accountInitial}>{me.user.first_name.charAt(0).toLocaleUpperCase()}</Text>
        </View>
        <Text style={styles.accountName}>{[me.user.first_name, me.user.last_name].filter(Boolean).join(" ")}</Text>
        <Text style={styles.accountEyebrow}>{t("profile.email")}</Text>
        <Text style={styles.accountValue}>{me.user.email}</Text>
        <View style={styles.accountDivider} />
        <Text style={styles.accountEyebrow}>{t("profile.cookStatus")}</Text>
        <Text style={styles.accountValue}>{hasCook ? t("profile.cookActive") : t("profile.cookInactive")}</Text>
      </View>
      <PrimaryButton icon="flame-outline" label={t("nav.cook")} onPress={openCookMode} />
      <Pressable accessibilityRole="button" onPress={() => void logout()} style={({ pressed }) => [styles.logoutButton, pressed && styles.pressed]}>
        <Ionicons color={colors.brandGreen} name="log-out-outline" size={19} />
        <Text style={styles.logoutText}>{t("auth.logout")}</Text>
      </Pressable>
    </View>
  );

  const activeTab: ClientTab = mode === "cook"
    ? "cook"
    : screen === "orders"
      ? "orders"
      : screen === "favorites"
        ? "favorites"
        : screen === "account"
          ? "profile"
          : "home";

  const screenContent = mode === "client" && (screen === "discover" || screen === "exploreFarther") && selectedDish ? (
    <DishDetail
      hasCart={cart.length > 0}
      onContinueShopping={continueShopping}
      replacementPending={pendingCartReplacement !== null}
      onCancelReplacement={() => setPendingCartReplacement(null)}
      onConfirmReplacement={replaceSelectedCart}
      cartQuantity={cart.find((line) => cartItemId(line.item) === cartItemId(selectedDish))?.quantity ?? 0}
      dish={selectedDish}
      favorite={profileFavorite}
      onAddToCart={addSelectedDishToCart}
      onBack={closeDishDetail}
      onOpenCook={() => void openProfile(selectedDish.cook_id)}
      onQuantityChange={setQuantity}
      onToggleFavorite={() => void toggleSelectedCookFavorite()}
      quantity={quantity}
    />
  ) : screen === "cart" ? (
    <CartScreen cart={cart} onBack={closeCart} onContinueShopping={continueShopping}
      onQuantity={(id, amount) => updateClientCart(changeCartQuantity(currentCart.current, id, amount))}
      onRemove={(id) => updateClientCart(removeCartItem(currentCart.current, id))}
      onContinue={continueCart} />
  ) : screen === "cartSummary" ? (
    <CartSummary lines={checkoutLines} merchantName={checkoutMerchantName} payment={payment} error={reservationError} busy={openingPayment}
      network={paymentNetwork} phone={paymentPhone} onNetwork={setPaymentNetwork} onPhone={setPaymentPhone}
      onPay={() => void startPayment()} onCheck={() => void checkPayment()}
      onOrders={() => void loadOrders("customer")} onHome={openClientMode} onBack={() => setScreen("cart")} />
  ) : screen === "exploreFarther" ? (
    <ExploreFartherScreen
      coordinates={searchCoordinates}
      locationLabel={locationLabel}
      onBack={() => setScreen("discover")}
      onOpenDish={openDish}
    />
  ) : screen === "cookProfile" ? (
    profileView
  ) : screen === "favorites" ? (
    favoritesView
  ) : screen === "orders" ? (
    orderView
  ) : screen === "account" ? (
    accountView
  ) : mode === "cook" ? (
    <View style={styles.page}>
      {modeSwitch}
      {cookView}
    </View>
  ) : (
    clientView
  );
  const showingClientHome = !selectedDish && screen === "discover" && mode === "client";
  const showBottomNavigation = screen !== "cart" && screen !== "cartSummary";

  return (
    <SafeAreaView edges={["top", "left", "right"]} style={styles.screen}>
      <StatusBar style="dark" />
      <View style={styles.appShell}>
        {showingClientHome ? (
          <View style={[styles.content, styles.fixedHomeContent, { paddingTop: spacing.sm + spacing.xxs }]}>
            {sectionLoading && <ActivityIndicator />}
            {sectionError && <Text style={styles.error}>{sectionError}</Text>}
            {screenContent}
          </View>
        ) : (
          <ScrollView
            alwaysBounceVertical={false}
            automaticallyAdjustContentInsets={false}
            bounces={false}
            contentInsetAdjustmentBehavior="never"
            contentContainerStyle={[styles.content, { paddingBottom: spacing.md, paddingTop: spacing.sm }]}
            keyboardShouldPersistTaps="handled"
            automaticallyAdjustKeyboardInsets={screen === "cartSummary"}
            keyboardDismissMode={screen === "cartSummary" ? "on-drag" : "none"}
            overScrollMode="never"
            ref={mainScrollRef}
            showsVerticalScrollIndicator={false}
            style={styles.mainScroll}
          >
            {sectionLoading && <ActivityIndicator />}
            {sectionError && <Text style={styles.error}>{sectionError}</Text>}
            {screenContent}
          </ScrollView>
        )}
        {mode === "client" && (screen === "discover" || (screen === "exploreFarther" && selectedDish !== null)) && <CartBar cart={cart} onPress={openCart} />}
        {showBottomNavigation && <View style={styles.bottomNavigationSlot}>
          <BottomNavigation
            active={activeTab}
            onSelect={selectClientTab}
          />
        </View>}
      </View>
      {me && mode === "client" && screen === "discover" && <LocationPickerModal
        visible={locationPickerVisible}
        choices={serviceAreas}
        selectedId={selectedLocationId}
        source={locationSource}
        detectedPositionSource={locationIssue === "outside_active_areas" || locationIssue === "no_active_service_areas"
          ? devicePosition?.source ?? null
          : null}
        loading={locationResolving}
        areasLoading={serviceAreasLoading}
        areasError={serviceAreasError}
        preferenceError={locationPreferenceError}
        gpsError={locationIssue ? locationIssueMessage(locationIssue, serviceAreas) : null}
        canOpenSettings={locationCanOpenSettings}
        onClose={() => setLocationPickerVisible(false)}
        onUseGps={() => void useCurrentLocationForDiscovery()}
        onOpenSettings={() => void Linking.openSettings()}
        onRetryAreas={() => void loadServiceAreas()}
        onSelect={(choice) => void selectManualLocation(choice)}
      />}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.warmCream },
  appShell: { flex: 1, minHeight: 0 },
  mainScroll: { flex: 1, minHeight: 0 },
  bottomNavigationSlot: { flexShrink: 0 },
  content: { flexGrow: 1, width: "100%", maxWidth: 680, alignSelf: "center", gap: spacing.sm, paddingHorizontal: spacing.sm, paddingTop: spacing.sm },
  fixedHomeContent: { flex: 1, minHeight: 0 },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.sm, backgroundColor: colors.warmCream },
  page: { gap: spacing.sm },
  clientHome: { minHeight: 0, flex: 1, gap: spacing.xs },
  modeSwitch: { flexDirection: "row", padding: 4, borderRadius: radius.md, backgroundColor: colors.creamDeep },
  modeButton: { flex: 1, minHeight: 44, alignItems: "center", justifyContent: "center", borderRadius: radius.sm, paddingVertical: 11 },
  modeButtonActive: { backgroundColor: colors.brandGreen },
  modeText: { color: colors.brandGreen, fontFamily: fonts.bold, fontSize: 14 },
  modeTextActive: { color: colors.warmCream },
  navigation: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  navigationText: { color: colors.brandGreen, fontFamily: fonts.bold, fontSize: 14 },
  buttonRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs },
  title: { color: colors.darkCocoa, fontFamily: fonts.editorialSemiBold, fontSize: 32, lineHeight: 38 },
  cardTitle: { color: colors.darkCocoa, fontFamily: fonts.editorialSemiBold, fontSize: 22 },
  subtitle: { marginTop: spacing.xs, color: colors.brandGreen, fontFamily: fonts.bold, fontSize: 18 },
  bodyText: { color: colors.cocoaMuted, fontFamily: fonts.regular, fontSize: 14, lineHeight: 21 },
  field: { gap: 6 },
  label: { color: colors.brandGreen, fontFamily: fonts.bold, fontSize: 13 },
  input: { minHeight: 48, borderWidth: 1, borderColor: colors.line, borderRadius: radius.sm, backgroundColor: colors.surface, color: colors.darkCocoa, fontFamily: fonts.regular, fontSize: 15, paddingHorizontal: 12, paddingVertical: 11 },
  primary: { alignSelf: "flex-start", minHeight: 48, justifyContent: "center", borderRadius: radius.pill, backgroundColor: colors.brandGreen, paddingHorizontal: spacing.md, paddingVertical: 12 },
  disabled: { opacity: 0.5 },
  primaryText: { color: colors.warmCream, fontFamily: fonts.bold, fontSize: 14 },
  secondary: { alignSelf: "flex-start", minHeight: 44, justifyContent: "center", borderWidth: 1, borderColor: colors.brandGreen, borderRadius: radius.sm, paddingHorizontal: 12, paddingVertical: 10 },
  card: { gap: spacing.xs, overflow: "hidden", marginTop: spacing.xs, borderWidth: 1, borderColor: colors.line, borderRadius: radius.lg, backgroundColor: colors.surface, padding: 14 },
  availability: { gap: 4, borderTopWidth: 1, borderTopColor: colors.line, paddingTop: spacing.xs },
  photo: { width: 100, height: 100, alignItems: "center", justifyContent: "center", gap: spacing.xxs, borderRadius: radius.md, backgroundColor: colors.cornYellow },
  photoLarge: { width: "100%", aspectRatio: 1.35, alignItems: "center", justifyContent: "center", gap: spacing.xs, borderRadius: radius.lg, backgroundColor: colors.cornYellow },
  photoPlaceholderText: { color: colors.brandGreen, fontFamily: fonts.semiBold, fontSize: 12 },
  preview: { width: "100%", height: 180, borderRadius: radius.md },
  pickupCode: { color: colors.brandGreen, fontFamily: fonts.extraBold, fontSize: 30, letterSpacing: 4 },
  error: { color: colors.error, fontFamily: fonts.semiBold, fontSize: 14 },
  success: { color: colors.success, fontFamily: fonts.semiBold, fontSize: 14 },
  heroCopy: { width: "100%", gap: 1, paddingTop: spacing.xxs, paddingBottom: spacing.xxs },
  heroGreeting: { marginBottom: spacing.xxs, color: colors.brandGreen, fontFamily: fonts.bold, fontSize: fontSizes.bodySmall, lineHeight: lineHeights.bodySmall },
  heroTitleBlock: { width: "100%", alignItems: "flex-start" },
  heroTitle: { flexShrink: 0, color: colors.ink, fontFamily: fonts.extraBold, fontSize: fontSizes.display, lineHeight: lineHeights.display, letterSpacing: -1 },
  heroTitleCompact: { fontSize: fontSizes.title, lineHeight: lineHeights.title, letterSpacing: -0.6 },
  searchBar: { minHeight: 52, flexDirection: "row", alignItems: "center", gap: spacing.xs, paddingHorizontal: spacing.sm, borderWidth: 1, borderColor: colors.line, borderRadius: radius.pill, backgroundColor: colors.warmSurface },
  searchInput: { flex: 1, minHeight: 48, color: colors.ink, fontFamily: fonts.regular, fontSize: 15, paddingVertical: 0 },
  searchClear: { width: 32, height: 32, alignItems: "center", justifyContent: "center" },
  heroAccent: { color: colors.mangoOrange },
  heroBody: { maxWidth: 340, marginTop: spacing.xs, color: colors.cocoaMuted, fontFamily: fonts.regular, fontSize: fontSizes.bodySmall, lineHeight: lineHeights.bodySmall },
  verticalSelector: { minHeight: 44, flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: spacing.xs },
  filterScroll: { width: "100%", height: 48, flexGrow: 0, flexShrink: 0 },
  filters: { alignItems: "center", gap: spacing.xs, paddingRight: spacing.sm },
  sectionHeading: { minHeight: controlSizes.minimumTouch, flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm },
  homeSectionTitle: { flex: 1, color: colors.ink, fontFamily: fonts.extraBold, fontSize: 22, lineHeight: 28, letterSpacing: -0.4 },
  refreshButton: { width: controlSizes.minimumTouch, height: controlSizes.minimumTouch, alignItems: "center", justifyContent: "center", borderRadius: radius.pill },
  filterEmpty: { minHeight: controlSizes.minimumTouch, flexDirection: "row", alignItems: "center", gap: spacing.xs, borderRadius: radius.lg, backgroundColor: colors.creamDeep, padding: spacing.sm },
  filterEmptyText: { flex: 1, color: colors.cocoaMuted, fontFamily: fonts.regular, fontSize: 14, lineHeight: 21 },
  dishResultsScroll: { minHeight: 0, flex: 1 },
  dishResultsContent: { flexGrow: 1, paddingBottom: spacing.md },
  dishList: { gap: spacing.md },
  accountCard: { alignItems: "center", gap: spacing.xs, borderRadius: radius.xl, backgroundColor: colors.surface, padding: spacing.md },
  accountAvatar: { width: 72, height: 72, alignItems: "center", justifyContent: "center", borderRadius: radius.pill, backgroundColor: colors.mutedSage },
  accountInitial: { color: colors.brandGreen, fontFamily: fonts.editorialBold, fontSize: 28 },
  accountName: { color: colors.darkCocoa, fontFamily: fonts.editorialSemiBold, fontSize: 25, textAlign: "center" },
  accountEyebrow: { marginTop: spacing.xs, color: colors.cocoaMuted, fontFamily: fonts.medium, fontSize: 11, textTransform: "uppercase", letterSpacing: 1 },
  accountValue: { color: colors.darkCocoa, fontFamily: fonts.semiBold, fontSize: 14, textAlign: "center" },
  accountDivider: { width: "100%", height: 1, marginVertical: spacing.xs, backgroundColor: colors.line },
  logoutButton: { minHeight: 48, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.xs, borderWidth: 1, borderColor: colors.brandGreen, borderRadius: radius.md },
  logoutText: { color: colors.brandGreen, fontFamily: fonts.bold, fontSize: 14 },
  pressed: { opacity: 0.7 },
});
