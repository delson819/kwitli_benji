import { useState } from "react";
import { ActivityIndicator, Image, Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { formatMoney } from "../format";
import { t } from "../i18n";
import { mediaUrl } from "../config";
import type { Availability, BusinessHour, BusinessVertical, CookProfile, Dish } from "../services/api";
import { colors } from "../theme/colors";
import { radius } from "../theme/radius";
import { spacing } from "../theme/spacing";
import { fonts } from "../theme/typography";
import { OrdersScreen, useMerchantOrdersMonitor } from "./OrdersScreen";

type ImageAsset = { uri: string; mimeType?: string | null; fileName?: string | null };
type MerchantSection = "dashboard" | "establishment" | "catalog" | "orders";
const WEEKDAY_KEYS = [
  "merchant.weekday.monday", "merchant.weekday.tuesday", "merchant.weekday.wednesday",
  "merchant.weekday.thursday", "merchant.weekday.friday", "merchant.weekday.saturday",
  "merchant.weekday.sunday",
] as const;
type EditDraft = {
  articleId: string;
  name: string;
  description: string;
  price: string;
  currency: string;
  category: string;
  isActive: boolean;
  photo: ImageAsset | null;
};
type AvailabilityDraft = {
  availabilityId: string;
  articleName: string;
  originalTotal: number;
  availableDate: string;
  startTime: string;
  endTime: string;
  stock: string;
  availabilityStatus: "active" | "inactive";
};

type Props = {
  profile: CookProfile | null;
  loading: boolean;
  publishingArticle: boolean;
  publishingAvailability: boolean;
  articles: Dish[];
  availabilities: Availability[];
  selectedAvailabilityArticle: Dish | null;
  profileName: string;
  profileBio: string;
  pickupLatitude: string;
  pickupLongitude: string;
  pickupAreaStatus: "inside" | "outside" | "unknown";
  pickupAreaLabel: string | null;
  articleName: string;
  articleDescription: string;
  articlePrice: string;
  availabilityDate: string;
  startTime: string;
  endTime: string;
  stockQuantity: string;
  profilePhoto: ImageAsset | null;
  articlePhoto: ImageAsset | null;
  currency: string;
  businessHours?: BusinessHour[];
  hoursSaving?: boolean;
  onProfileNameChange: (value: string) => void;
  onProfileBioChange: (value: string) => void;
  onPickupLatitudeChange: (value: string) => void;
  onPickupLongitudeChange: (value: string) => void;
  onArticleNameChange: (value: string) => void;
  onArticleDescriptionChange: (value: string) => void;
  onArticlePriceChange: (value: string) => void;
  onAvailabilityDateChange: (value: string) => void;
  onStartTimeChange: (value: string) => void;
  onEndTimeChange: (value: string) => void;
  onStockQuantityChange: (value: string) => void;
  onUseCurrentLocation: () => void;
  onCreateProfile: () => void;
  onSaveProfile: () => void;
  onBusinessHourChange?: (weekday: number, values: Partial<Pick<BusinessHour, "is_closed" | "opens_at" | "closes_at">>) => void;
  onSaveBusinessHours?: () => void;
  onSavePickup: () => void;
  onPickProfilePhoto: (camera: boolean) => void;
  onReplaceProfilePhoto: (camera: boolean) => void;
  onPickArticlePhoto: (camera: boolean) => void;
  onPickEditArticlePhoto: (camera: boolean) => Promise<ImageAsset | null>;
  onSaveEditArticlePhoto: (articleId: string, asset: ImageAsset) => Promise<void>;
  onSelectAvailabilityArticle: (articleId: string | null) => void;
  onPublishArticle: (options: { category: string | null; is_active: boolean }) => Promise<boolean>;
  onCancelNewArticle: () => void;
  onPublishAvailability: (status: "active" | "inactive") => void;
  onUpdateArticle: (articleId: string, payload: { name?: string; description?: string; price?: string; category?: string | null; is_active?: boolean }) => Promise<void>;
  onUpdateAvailability: (availabilityId: string, payload: { available_date?: string; start_time?: string; end_time?: string; total_portions?: number; remaining_portions?: number; status?: "active" | "inactive" }) => Promise<void>;
};

function MerchantInput({
  label,
  value,
  onChangeText,
  numeric = false,
  allowNegative = false,
}: {
  label: string;
  value: string;
  onChangeText: (value: string) => void;
  numeric?: boolean;
  allowNegative?: boolean;
}) {
  return <View style={styles.field}>
    <Text style={styles.label}>{label}</Text>
    <TextInput
      keyboardType={allowNegative ? "default" : numeric ? "decimal-pad" : "default"}
      onChangeText={onChangeText}
      style={styles.input}
      value={value}
    />
  </View>;
}

function PickupAreaNotice({
  status,
  areaLabel,
}: {
  status: "inside" | "outside" | "unknown";
  areaLabel: string | null;
}) {
  if (status === "inside") {
    return <Text style={styles.muted}>{t("merchant.pickupInsideActiveArea", { area: areaLabel ?? "" })}</Text>;
  }
  if (status === "outside") {
    return <Text style={styles.inactive}>{t("merchant.pickupOutsideActiveArea")}</Text>;
  }
  return <Text style={styles.muted}>{t("merchant.pickupAreaUnknown")}</Text>;
}

function MerchantPhoto({ uri, large = false }: { uri: string | null; large?: boolean }) {
  if (uri) return <Image source={{ uri: mediaUrl(uri) }} style={large ? styles.photoLarge : styles.photo} />;
  return <View style={large ? styles.photoLarge : styles.photo}>
    <Text style={styles.photoPlaceholder}>{t("merchant.photoPlaceholder")}</Text>
  </View>;
}

function MerchantAction({ label, onPress, primary = false, disabled = false }: {
  label: string;
  onPress: () => void;
  primary?: boolean;
  disabled?: boolean;
}) {
  return <Pressable
    accessibilityRole="button"
    disabled={disabled}
    onPress={onPress}
    style={({ pressed }) => [primary ? styles.primary : styles.secondary, pressed && !disabled && styles.pressed, disabled && styles.disabled]}
  >
    <Text style={primary ? styles.primaryText : styles.secondaryText}>{label}</Text>
  </Pressable>;
}

function MerchantToggle({ label, onPress, selected, disabled = false }: {
  label: string;
  onPress: () => void;
  selected: boolean;
  disabled?: boolean;
}) {
  return <Pressable
    accessibilityRole="button"
    accessibilityState={{ selected, disabled }}
    disabled={disabled}
    onPress={onPress}
    style={({ pressed }) => [selected ? styles.primary : styles.secondary, pressed && !disabled && styles.pressed, disabled && styles.disabled]}
  >
    <Text style={selected ? styles.primaryText : styles.secondaryText}>{label}</Text>
  </Pressable>;
}

function verticalLabel(vertical: BusinessVertical | null | undefined): string {
  if (vertical === "bakery_dessert") return t("merchant.vertical.bakeryDessert");
  if (vertical === "local_shop") return t("merchant.vertical.localShop");
  return t("merchant.vertical.foodService");
}

function catalogLabel(vertical: BusinessVertical | null | undefined): string {
  if (vertical === "food_service") return t("merchant.catalog.foodService");
  return t("merchant.catalog.generic");
}

function articleLabel(vertical: BusinessVertical | null | undefined): string {
  if (vertical === "bakery_dessert") return t("merchant.article.bakeryDessert");
  if (vertical === "local_shop") return t("merchant.article.localShop");
  return t("merchant.article.foodService");
}

function currencyLabel(currency: string): string {
  return currency === "XOF" ? t("currency.xof.short") : currency;
}

export function MerchantDashboard({
  profile,
  loading,
  publishingArticle,
  publishingAvailability,
  articles,
  availabilities,
  selectedAvailabilityArticle,
  profileName,
  profileBio,
  pickupLatitude,
  pickupLongitude,
  pickupAreaStatus,
  pickupAreaLabel,
  articleName,
  articleDescription,
  articlePrice,
  availabilityDate,
  startTime,
  endTime,
  stockQuantity,
  profilePhoto,
  articlePhoto,
  currency,
  businessHours,
  hoursSaving = false,
  onProfileNameChange,
  onProfileBioChange,
  onPickupLatitudeChange,
  onPickupLongitudeChange,
  onArticleNameChange,
  onArticleDescriptionChange,
  onArticlePriceChange,
  onAvailabilityDateChange,
  onStartTimeChange,
  onEndTimeChange,
  onStockQuantityChange,
  onUseCurrentLocation,
  onCreateProfile,
  onSaveProfile,
  onBusinessHourChange,
  onSaveBusinessHours,
  onSavePickup,
  onPickProfilePhoto,
  onReplaceProfilePhoto,
  onPickArticlePhoto,
  onPickEditArticlePhoto,
  onSaveEditArticlePhoto,
  onSelectAvailabilityArticle,
  onPublishArticle,
  onCancelNewArticle,
  onPublishAvailability,
  onUpdateArticle,
  onUpdateAvailability,
}: Props) {
  const [section, setSection] = useState<MerchantSection>("dashboard");
  const [articleFormVisible, setArticleFormVisible] = useState(false);
  const [editDraft, setEditDraft] = useState<EditDraft | null>(null);
  const [availabilityDraft, setAvailabilityDraft] = useState<AvailabilityDraft | null>(null);
  const [savingEdit, setSavingEdit] = useState(false);
  const merchantFeed = useMerchantOrdersMonitor(profile?.id ?? null);
  const [createCategory, setCreateCategory] = useState("");
  const [createIsActive, setCreateIsActive] = useState(true);
  const [createAvailabilityStatus, setCreateAvailabilityStatus] = useState<"active" | "inactive">("active");
  const [availabilityDraftError, setAvailabilityDraftError] = useState<string | null>(null);
  const businessVertical = profile?.business_vertical ?? "food_service";
  const currentCatalogLabel = catalogLabel(businessVertical);
  const currentArticleLabel = articleLabel(businessVertical);
  const displayCurrency = currencyLabel(currency);
  const pickupLatitudeNumber = Number(pickupLatitude);
  const pickupLongitudeNumber = Number(pickupLongitude);
  const displayedPickupLatitude = Number.isFinite(pickupLatitudeNumber) ? pickupLatitudeNumber : profile?.latitude;
  const displayedPickupLongitude = Number.isFinite(pickupLongitudeNumber) ? pickupLongitudeNumber : profile?.longitude;

  function openSection(next: MerchantSection) {
    setSection(next);
    if (next === "orders") merchantFeed.markSeen();
    if (next !== "catalog") {
      if (articleFormVisible) onCancelNewArticle();
      setArticleFormVisible(false);
      setEditDraft(null);
      setAvailabilityDraft(null);
      if (selectedAvailabilityArticle) onSelectAvailabilityArticle(null);
    }
  }

  function openEditArticle(article: Dish) {
    setArticleFormVisible(false);
    setAvailabilityDraft(null);
    if (selectedAvailabilityArticle) onSelectAvailabilityArticle(null);
    setEditDraft({
      articleId: article.id,
      name: article.name,
      description: article.description,
      price: article.price,
      currency: article.currency,
      category: article.category ?? "",
      isActive: article.is_active,
      photo: null,
    });
  }

  function openEditAvailability(article: Dish, availability: Availability) {
    setArticleFormVisible(false);
    setEditDraft(null);
    if (selectedAvailabilityArticle) onSelectAvailabilityArticle(null);
    setAvailabilityDraftError(null);
    setAvailabilityDraft({
      availabilityId: availability.id,
      articleName: article.name,
      originalTotal: availability.total_portions,
      availableDate: availability.available_date,
      startTime: availability.start_time,
      endTime: availability.end_time,
      stock: String(availability.remaining_portions),
      availabilityStatus: availability.status === "inactive" ? "inactive" : "active",
    });
  }

  function updateDraft(values: Partial<EditDraft>) {
    setEditDraft((current) => current ? { ...current, ...values } : current);
  }

  async function pickEditArticlePhoto(camera: boolean) {
    const articleId = editDraft?.articleId;
    if (!articleId) return;
    const asset = await onPickEditArticlePhoto(camera);
    if (asset) setEditDraft((current) => current?.articleId === articleId ? { ...current, photo: asset } : current);
  }

  function updateAvailabilityDraft(values: Partial<AvailabilityDraft>) {
    setAvailabilityDraft((current) => current ? { ...current, ...values } : current);
  }

  async function saveEditDraft() {
    if (!editDraft) return;
    const draft = editDraft;
    setSavingEdit(true);
    try {
      await onUpdateArticle(draft.articleId, {
        name: draft.name.trim(),
        description: draft.description.trim(),
        // Accepter « 1 500 » et « 1500,50 » comme on les tape en francais.
        price: draft.price.replace(/[\s  ]/g, "").replace(",", "."),
        category: draft.category.trim() || null,
        is_active: draft.isActive,
      });
      if (draft.photo) await onSaveEditArticlePhoto(draft.articleId, draft.photo);
      setEditDraft(null);
    } catch {
      setEditDraft(draft);
    } finally {
      setSavingEdit(false);
    }
  }

  async function saveAvailabilityDraft() {
    if (!availabilityDraft) return;
    const draft = availabilityDraft;
    const stock = Number(draft.stock.trim());
    if (!draft.stock.trim() || !Number.isInteger(stock) || stock < 0) {
      setAvailabilityDraftError(t("merchant.stockInvalid"));
      return;
    }
    setAvailabilityDraftError(null);
    setSavingEdit(true);
    try {
      await onUpdateAvailability(draft.availabilityId, {
        available_date: draft.availableDate,
        start_time: draft.startTime,
        end_time: draft.endTime,
        total_portions: Math.max(draft.originalTotal, stock),
        remaining_portions: stock,
        status: draft.availabilityStatus,
      });
      setAvailabilityDraft(null);
    } catch {
      setAvailabilityDraft(draft);
    } finally {
      setSavingEdit(false);
    }
  }

  function openCreateAvailability(articleId: string) {
    setArticleFormVisible(false);
    setEditDraft(null);
    setAvailabilityDraft(null);
    setCreateAvailabilityStatus("active");
    onSelectAvailabilityArticle(articleId);
  }

  const availabilityForm = selectedAvailabilityArticle ? <View style={styles.subCard}>
    <Text style={styles.sectionTitle}>{t("merchant.availabilityForArticle")}</Text>
    <Text style={styles.cardTitle}>{selectedAvailabilityArticle.name}</Text>
    <MerchantInput label={t("merchant.date")} value={availabilityDate} onChangeText={onAvailabilityDateChange} />
    <MerchantInput label={t("merchant.startTime")} value={startTime} onChangeText={onStartTimeChange} />
    <MerchantInput label={t("merchant.endTime")} value={endTime} onChangeText={onEndTimeChange} />
    <MerchantInput label={t("merchant.portionsAvailable")} value={stockQuantity} onChangeText={onStockQuantityChange} numeric />
    <View style={styles.actions}>
      <MerchantToggle selected={createAvailabilityStatus === "active"} label={t("merchant.activeAvailability")} onPress={() => setCreateAvailabilityStatus("active")} />
      <MerchantToggle selected={createAvailabilityStatus === "inactive"} label={t("merchant.inactiveAvailability")} onPress={() => setCreateAvailabilityStatus("inactive")} />
    </View>
    <View style={styles.actions}>
      <MerchantAction disabled={publishingAvailability} primary label={publishingAvailability ? t("merchant.creating") : t("merchant.addAvailability")} onPress={() => onPublishAvailability(createAvailabilityStatus)} />
      <MerchantAction disabled={publishingAvailability} label={t("common.cancel")} onPress={() => onSelectAvailabilityArticle(null)} />
    </View>
  </View> : null;

  const establishmentView = <View style={styles.section}>
    <View style={styles.sectionHeader}>
      <Text style={styles.sectionTitle}>{t("merchant.establishment")}</Text>
      <MerchantAction label={t("merchant.backToDashboard")} onPress={() => openSection("dashboard")} />
    </View>
    {profile ? <View style={styles.card}>
      <MerchantPhoto uri={profile.profile_photo_url} large />
      <MerchantInput label={t("merchant.establishmentName")} value={profileName} onChangeText={onProfileNameChange} />
      <MerchantInput label={t("merchant.establishmentDescription")} value={profileBio} onChangeText={onProfileBioChange} />
      <Text style={styles.muted}>{t("merchant.descriptionHint")}</Text>
      <View style={styles.metaRow}>
        <Text style={styles.metaLabel}>{t("merchant.businessVertical")}</Text>
        <Text style={styles.metaValue}>{verticalLabel(profile.business_vertical)}</Text>
      </View>
      <View style={styles.metaRow}>
        <Text style={styles.metaLabel}>{t("merchant.pickupPoint")}</Text>
        <Text style={styles.metaValue}>{displayedPickupLatitude?.toFixed(5)}, {displayedPickupLongitude?.toFixed(5)}</Text>
      </View>
      <Text style={styles.muted}>{t("merchant.pickupCoordinatesHint")}</Text>
      <PickupAreaNotice status={pickupAreaStatus} areaLabel={pickupAreaLabel} />
      <View style={styles.metaRow}>
        <Text style={styles.metaLabel}>{t("merchant.profileStatus")}</Text>
        <Text style={styles.metaValue}>{profile.is_verified ? t("merchant.verified") : t("merchant.pendingProfile")}</Text>
      </View>
      <Text style={styles.muted}>{profile.is_verified ? t("merchant.verifiedHint") : t("merchant.pendingProfileHint")}</Text>
      <MerchantAction primary label={t("merchant.saveProfile")} onPress={onSaveProfile} />
      <View style={styles.subCard}>
        <Text style={styles.sectionTitle}>{t("merchant.businessHours")}</Text>
        <Text style={styles.muted}>{t("merchant.businessHoursHint")}</Text>
        {(businessHours ?? []).map((day) => <View key={day.weekday} style={styles.hourDay}>
          <Text style={styles.metaValue}>{t(WEEKDAY_KEYS[day.weekday])}</Text>
          <View style={styles.actions}>
            <MerchantToggle selected={!day.is_closed} label={t("merchant.openDay")}
              onPress={() => onBusinessHourChange?.(day.weekday, { is_closed: false, opens_at: day.opens_at ?? "10:00:00", closes_at: day.closes_at ?? "20:00:00" })} />
            <MerchantToggle selected={day.is_closed} label={t("merchant.closedDay")}
              onPress={() => onBusinessHourChange?.(day.weekday, { is_closed: true, opens_at: null, closes_at: null })} />
          </View>
          {!day.is_closed && <View style={styles.actions}>
            <MerchantInput label={t("merchant.openingTime")} value={(day.opens_at ?? "").slice(0, 5)} onChangeText={(value) => onBusinessHourChange?.(day.weekday, { opens_at: value.length === 5 ? `${value}:00` : value })} />
            <MerchantInput label={t("merchant.closingTime")} value={(day.closes_at ?? "").slice(0, 5)} onChangeText={(value) => onBusinessHourChange?.(day.weekday, { closes_at: value.length === 5 ? `${value}:00` : value })} />
          </View>}
        </View>)}
        <MerchantAction disabled={hoursSaving} primary label={hoursSaving ? t("common.loading") : t("merchant.saveBusinessHours")} onPress={() => onSaveBusinessHours?.()} />
      </View>
      <MerchantInput label={t("merchant.pickupLatitude")} value={pickupLatitude} onChangeText={onPickupLatitudeChange} numeric allowNegative />
      <MerchantInput label={t("merchant.pickupLongitude")} value={pickupLongitude} onChangeText={onPickupLongitudeChange} numeric allowNegative />
      <PickupAreaNotice status={pickupAreaStatus} areaLabel={pickupAreaLabel} />
      <View style={styles.actions}>
        <MerchantAction label={t("merchant.proposeCurrentPosition")} onPress={onUseCurrentLocation} />
        <MerchantAction label={t("merchant.savePickup")} onPress={onSavePickup} />
        <MerchantAction label={t("merchant.changeProfilePhoto")} onPress={() => onReplaceProfilePhoto(false)} />
        <MerchantAction label={t("photo.camera")} onPress={() => onReplaceProfilePhoto(true)} />
      </View>
    </View> : <View style={styles.card}>
      <Text style={styles.cardTitle}>{t("merchant.createEstablishment")}</Text>
      <MerchantInput label={t("merchant.establishmentName")} value={profileName} onChangeText={onProfileNameChange} />
      <MerchantInput label={t("merchant.establishmentDescription")} value={profileBio} onChangeText={onProfileBioChange} />
      <Text style={styles.muted}>{t("merchant.descriptionHint")}</Text>
      <MerchantInput label={t("merchant.pickupLatitude")} value={pickupLatitude} onChangeText={onPickupLatitudeChange} numeric allowNegative />
      <MerchantInput label={t("merchant.pickupLongitude")} value={pickupLongitude} onChangeText={onPickupLongitudeChange} numeric allowNegative />
      <View style={styles.actions}>
        <MerchantAction label={t("merchant.proposeCurrentPosition")} onPress={onUseCurrentLocation} />
        <MerchantAction label={t("photo.camera")} onPress={() => onPickProfilePhoto(true)} />
        <MerchantAction label={t("photo.gallery")} onPress={() => onPickProfilePhoto(false)} />
      </View>
      {profilePhoto && <Image source={{ uri: profilePhoto.uri }} style={styles.preview} />}
      <MerchantAction primary label={t("merchant.createEstablishment")} onPress={onCreateProfile} />
    </View>}
  </View>;

  const articleForm = <View style={styles.card}>
    <Text style={styles.cardTitle}>{t("merchant.addArticle")}</Text>
    <MerchantInput label={t("merchant.articleName")} value={articleName} onChangeText={onArticleNameChange} />
    <MerchantInput label={t("merchant.description")} value={articleDescription} onChangeText={onArticleDescriptionChange} />
    <MerchantInput label={t("merchant.priceWithCurrency", { currency: displayCurrency })} value={articlePrice} onChangeText={onArticlePriceChange} numeric />
    <MerchantInput label={t("merchant.articleCategory")} value={createCategory} onChangeText={setCreateCategory} />
    <View style={styles.actions}>
      <MerchantToggle selected={createIsActive} label={t("merchant.activeArticle")} onPress={() => setCreateIsActive(true)} />
      <MerchantToggle selected={!createIsActive} label={t("merchant.inactiveArticle")} onPress={() => setCreateIsActive(false)} />
    </View>
    <View style={styles.actions}>
      <MerchantAction disabled={publishingArticle} label={t("photo.camera")} onPress={() => onPickArticlePhoto(true)} />
      <MerchantAction disabled={publishingArticle} label={t("photo.gallery")} onPress={() => onPickArticlePhoto(false)} />
      <MerchantAction disabled={publishingArticle} label={t("common.cancel")} onPress={() => { onCancelNewArticle(); setArticleFormVisible(false); }} />
    </View>
    {articlePhoto && <Image source={{ uri: articlePhoto.uri }} style={styles.preview} />}
    <MerchantAction disabled={publishingArticle} primary label={publishingArticle ? t("merchant.creating") : t("merchant.addArticle")} onPress={() => void onPublishArticle({ category: createCategory.trim() || null, is_active: createIsActive }).then((created) => { if (created) setArticleFormVisible(false); })} />
  </View>;

  const editForm = editDraft ? <View style={styles.card}>
    <Text style={styles.cardTitle}>{t("merchant.editArticle")}</Text>
    <MerchantInput label={t("merchant.articleName")} value={editDraft.name} onChangeText={(value) => updateDraft({ name: value })} />
    <MerchantInput label={t("merchant.description")} value={editDraft.description} onChangeText={(value) => updateDraft({ description: value })} />
    <MerchantInput label={t("merchant.priceWithCurrency", { currency: currencyLabel(editDraft.currency) })} value={editDraft.price} onChangeText={(value) => updateDraft({ price: value })} numeric />
    <MerchantInput label={t("merchant.articleCategory")} value={editDraft.category} onChangeText={(value) => updateDraft({ category: value })} />
    <View style={styles.actions}>
      <MerchantToggle disabled={savingEdit} selected={editDraft.isActive} label={t("merchant.activeArticle")} onPress={() => updateDraft({ isActive: true })} />
      <MerchantToggle disabled={savingEdit} selected={!editDraft.isActive} label={t("merchant.inactiveArticle")} onPress={() => updateDraft({ isActive: false })} />
    </View>
    <View style={styles.actions}>
      <MerchantAction disabled={savingEdit} label={t("photo.camera")} onPress={() => void pickEditArticlePhoto(true)} />
      <MerchantAction disabled={savingEdit} label={t("photo.gallery")} onPress={() => void pickEditArticlePhoto(false)} />
    </View>
    {editDraft.photo
      ? <Image source={{ uri: editDraft.photo.uri }} style={styles.preview} />
      : articles.find((article) => article.id === editDraft.articleId)?.photo_url
        ? <MerchantPhoto uri={articles.find((article) => article.id === editDraft.articleId)?.photo_url ?? null} large />
        : null}
    <View style={styles.actions}>
      <MerchantAction disabled={savingEdit} primary label={t("merchant.saveArticle")} onPress={() => void saveEditDraft()} />
      <MerchantAction disabled={savingEdit} label={t("common.cancel")} onPress={() => setEditDraft(null)} />
    </View>
  </View> : null;

  const editAvailabilityForm = availabilityDraft ? <View style={styles.card}>
    <Text style={styles.cardTitle}>{t("merchant.editAvailability")}</Text>
    <Text style={styles.muted}>{availabilityDraft.articleName}</Text>
    <MerchantInput label={t("merchant.date")} value={availabilityDraft.availableDate} onChangeText={(value) => updateAvailabilityDraft({ availableDate: value })} />
    <MerchantInput label={t("merchant.startTime")} value={availabilityDraft.startTime} onChangeText={(value) => updateAvailabilityDraft({ startTime: value })} />
    <MerchantInput label={t("merchant.endTime")} value={availabilityDraft.endTime} onChangeText={(value) => updateAvailabilityDraft({ endTime: value })} />
    <MerchantInput label={t("merchant.portionsAvailable")} value={availabilityDraft.stock} onChangeText={(value) => updateAvailabilityDraft({ stock: value })} numeric />
    {!!availabilityDraftError && <Text accessibilityRole="alert" style={styles.inactive}>{availabilityDraftError}</Text>}
    <View style={styles.actions}>
      <MerchantToggle disabled={savingEdit} selected={availabilityDraft.availabilityStatus === "active"} label={t("merchant.activeAvailability")} onPress={() => updateAvailabilityDraft({ availabilityStatus: "active" })} />
      <MerchantToggle disabled={savingEdit} selected={availabilityDraft.availabilityStatus === "inactive"} label={t("merchant.inactiveAvailability")} onPress={() => updateAvailabilityDraft({ availabilityStatus: "inactive" })} />
    </View>
    <View style={styles.actions}>
      <MerchantAction disabled={savingEdit} primary label={t("common.save")} onPress={() => void saveAvailabilityDraft()} />
      <MerchantAction disabled={savingEdit} label={t("common.cancel")} onPress={() => setAvailabilityDraft(null)} />
    </View>
  </View> : null;

  const catalogView = <View style={styles.section}>
    <View style={styles.sectionHeader}>
      <Text style={styles.sectionTitle}>{currentCatalogLabel}</Text>
      <MerchantAction label={t("merchant.backToDashboard")} onPress={() => openSection("dashboard")} />
    </View>
    <View style={styles.sectionHeader}>
      <Text style={styles.muted}>{t("merchant.catalogHint", { article: currentArticleLabel })}</Text>
      {loading && <ActivityIndicator color={colors.brandGreen} />}
    </View>
    {!loading && articles.length === 0 && <Text style={styles.muted}>{t("merchant.noArticles")}</Text>}
    {articles.map((article) => {
      return <View key={article.id} style={styles.card}>
        <View style={styles.articleRow}>
          <MerchantPhoto uri={article.photo_url} />
          <View style={styles.articleText}>
            <Text style={styles.cardTitle}>{article.name}</Text>
            <Text style={styles.price}>{formatMoney(article.price, article.currency)}</Text>
            {article.category ? <Text style={styles.badge}>{article.category}</Text> : null}
            <Text style={article.is_active ? styles.active : styles.inactive}>
              {article.is_active ? t("merchant.activeArticle") : t("merchant.inactiveArticle")}
            </Text>
          </View>
        </View>
        <View style={styles.actions}>
          <MerchantAction primary label={t("merchant.editArticle")} onPress={() => openEditArticle(article)} />
        </View>
        {editDraft?.articleId === article.id && editForm}
      </View>;
    })}
    {!articleFormVisible && <MerchantAction primary label={t("merchant.addArticle")} onPress={() => {
      setEditDraft(null);
      setAvailabilityDraft(null);
      if (selectedAvailabilityArticle) onSelectAvailabilityArticle(null);
      setCreateCategory("");
      setCreateIsActive(true);
      setArticleFormVisible(true);
    }} />}
    {articleFormVisible && articleForm}
  </View>;

  const ordersView = <View style={styles.section}>
    <View style={styles.sectionHeader}>
      <Text style={styles.sectionTitle}>{t("merchant.receivedOrders")}</Text>
      <MerchantAction label={t("merchant.backToDashboard")} onPress={() => openSection("dashboard")} />
    </View>
  </View>;

  return <View style={styles.container}>
    <View style={styles.hero}>
      <Text style={styles.eyebrow}>{t("merchant.eyebrow")}</Text>
      <Text style={styles.title}>{t("merchant.dashboard")}</Text>
      <Text style={styles.body}>{t("merchant.dashboardBody")}</Text>
    </View>

    {section !== "orders" && merchantFeed.arrivals > 0 && <Pressable accessibilityRole="button" accessibilityLiveRegion="polite"
      style={styles.entryCard} onPress={() => openSection("orders")}>
      <Text style={styles.cardTitle}>{t(merchantFeed.arrivals === 1 ? "orders.arrivalOne" : "orders.arrivalMany", { count: merchantFeed.arrivals })}</Text>
      <Text style={styles.muted}>{t("merchant.receivedOrders")}</Text>
    </Pressable>}

    {section === "dashboard" && <View style={styles.section}>
      <Pressable accessibilityRole="button" onPress={() => openSection("establishment")} style={({ pressed }) => [styles.entryCard, pressed && styles.pressed]}>
        <Text style={styles.cardTitle}>{t("merchant.establishment")}</Text>
        <Text style={styles.muted}>{profile ? profile.display_name : t("merchant.createEstablishment")}</Text>
      </Pressable>
      {profile && <Pressable accessibilityRole="button" onPress={() => openSection("catalog")} style={({ pressed }) => [styles.entryCard, pressed && styles.pressed]}>
        <Text style={styles.cardTitle}>{currentCatalogLabel}</Text>
        <Text style={styles.muted}>{t("merchant.catalogOverview", { count: articles.length, article: currentArticleLabel })}</Text>
      </Pressable>}
      {profile && <Pressable accessibilityRole="button" onPress={() => openSection("orders")} style={({ pressed }) => [styles.entryCard, pressed && styles.pressed]}>
        <Text style={styles.cardTitle}>{t("merchant.receivedOrders")}</Text>
        <Text style={styles.muted}>{merchantFeed.arrivals > 0
          ? t(merchantFeed.arrivals === 1 ? "orders.arrivalOne" : "orders.arrivalMany", { count: merchantFeed.arrivals })
          : t("merchant.ordersOverview")}</Text>
      </Pressable>}
    </View>}
    {section === "establishment" && establishmentView}
    {section === "catalog" && profile && catalogView}
    {section === "orders" && profile && ordersView}
    {profile && <OrdersScreen key={profile.id} scope="cook" refreshKey={0} onReview={() => undefined}
      visible={section === "orders"} merchantFeed={merchantFeed} />}
  </View>;
}

const styles = StyleSheet.create({
  container: { gap: spacing.md },
  hero: { gap: spacing.xs, padding: spacing.md, borderRadius: radius.xl, backgroundColor: colors.surface },
  eyebrow: { color: colors.mangoOrange, fontFamily: fonts.extraBold, fontSize: 12, letterSpacing: 1, textTransform: "uppercase" },
  title: { color: colors.darkCocoa, fontFamily: fonts.editorialBold, fontSize: 31, lineHeight: 37 },
  body: { color: colors.darkCocoa, fontFamily: fonts.regular, fontSize: 15, lineHeight: 23 },
  muted: { color: colors.cocoaMuted, fontFamily: fonts.regular, fontSize: 14, lineHeight: 21 },
  section: { gap: spacing.sm },
  hourDay: { gap: spacing.xs, paddingVertical: spacing.xs, borderBottomWidth: 1, borderBottomColor: colors.line },
  sectionHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm },
  sectionTitle: { color: colors.brandGreen, fontFamily: fonts.bold, fontSize: 19 },
  smallTitle: { color: colors.brandGreen, fontFamily: fonts.bold, fontSize: 14 },
  card: { gap: spacing.sm, padding: spacing.md, borderWidth: 1, borderColor: colors.line, borderRadius: radius.lg, backgroundColor: colors.surface },
  entryCard: { gap: spacing.xs, padding: spacing.md, borderWidth: 1, borderColor: colors.line, borderRadius: radius.lg, backgroundColor: colors.surface },
  subCard: { gap: spacing.sm, padding: spacing.md, borderWidth: 1, borderColor: colors.mutedSage, borderRadius: radius.lg, backgroundColor: colors.warmSurface },
  cardTitle: { color: colors.darkCocoa, fontFamily: fonts.editorialSemiBold, fontSize: 22 },
  field: { gap: 6 },
  label: { color: colors.brandGreen, fontFamily: fonts.bold, fontSize: 13 },
  input: { minHeight: 48, borderWidth: 1, borderColor: colors.line, borderRadius: radius.sm, backgroundColor: colors.surface, color: colors.darkCocoa, fontFamily: fonts.regular, fontSize: 15, paddingHorizontal: 12, paddingVertical: 11 },
  actions: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs },
  primary: { alignSelf: "flex-start", minHeight: 48, justifyContent: "center", borderRadius: radius.pill, backgroundColor: colors.brandGreen, paddingHorizontal: spacing.md, paddingVertical: 12 },
  secondary: { alignSelf: "flex-start", minHeight: 44, justifyContent: "center", borderWidth: 1, borderColor: colors.brandGreen, borderRadius: radius.sm, paddingHorizontal: 12, paddingVertical: 10 },
  primaryText: { color: colors.warmCream, fontFamily: fonts.bold, fontSize: 14 },
  secondaryText: { color: colors.brandGreen, fontFamily: fonts.bold, fontSize: 14 },
  disabled: { opacity: 0.5 },
  pressed: { opacity: 0.7 },
  photo: { width: 96, height: 96, alignItems: "center", justifyContent: "center", borderRadius: radius.md, backgroundColor: colors.cornYellow, padding: spacing.xs },
  photoLarge: { width: "100%", aspectRatio: 1.55, alignItems: "center", justifyContent: "center", borderRadius: radius.lg, backgroundColor: colors.cornYellow, padding: spacing.sm },
  photoPlaceholder: { color: colors.brandGreen, fontFamily: fonts.semiBold, fontSize: 12, textAlign: "center" },
  preview: { width: "100%", height: 180, borderRadius: radius.md },
  metaRow: { gap: 2, paddingTop: spacing.xs, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.line },
  metaLabel: { color: colors.cocoaMuted, fontFamily: fonts.medium, fontSize: 12 },
  metaValue: { color: colors.darkCocoa, fontFamily: fonts.semiBold, fontSize: 14 },
  articleRow: { flexDirection: "row", gap: spacing.sm, alignItems: "center" },
  articleText: { flex: 1, gap: spacing.xxs },
  price: { color: colors.brandGreen, fontFamily: fonts.extraBold, fontSize: 18 },
  badge: { alignSelf: "flex-start", color: colors.darkCocoa, fontFamily: fonts.semiBold, fontSize: 12, borderRadius: radius.pill, backgroundColor: colors.creamDeep, paddingHorizontal: spacing.xs, paddingVertical: spacing.xxs },
  active: { color: colors.success, fontFamily: fonts.bold, fontSize: 13 },
  inactive: { color: colors.error, fontFamily: fonts.bold, fontSize: 13 },
  availability: { gap: 4, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.line, paddingTop: spacing.xs },
});
