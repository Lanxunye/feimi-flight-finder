"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { airports, cityMap, cityOptions, type City, type CityOption } from "./airports";
import { buildBookingReference } from "./booking-reference";

type SelectionTarget = "origin" | "transfer" | "destination";
type PickerMode = "city" | "airport";
type Segment = {
  from: City;
  to: City;
  departTime: string;
  arriveTime: string;
  departDate?: string;
  arriveDate?: string;
  flightNo: string;
  airline: string;
  durationMinutes: number;
};
type PriceEvidence = {
  source: string;
  provider?: string;
  checkId?: string;
  price: number;
  checkedAt: string;
  url?: string;
};
type Offer = {
  id: string;
  price: number;
  provider: string;
  tags: string[];
  segments: Segment[];
  transferMinutes: number | null;
  totalMinutes: number;
  crossDay?: boolean;
  purchaseUrl: string;
  updatedAt: string;
  evidence?: PriceEvidence[];
  throughFlight?: boolean;
  throughServices?: string[];
};
type SearchResponse = {
  offers: Offer[];
  mode: "verified" | "unavailable";
  searchedAt: string;
  message?: string;
};
type SearchContext = {
  origin: string;
  originCity: string;
  destination: string;
  destinationCity: string;
  transfer: string | null;
  transferCity: string | null;
  date: string;
  throughOnly: boolean;
};
type OtaProviderKey = "ctrip" | "qunar" | "meituan";
type OtaStatus = {
  available?: boolean;
  providers?: Partial<Record<OtaProviderKey, { label: string; connected: boolean }>>;
  message?: string;
};
type AlertStatus = {
  available: boolean;
  desktopOnly?: boolean;
  enabled: boolean;
  recipientConfigured?: boolean;
  recipientMasked?: string;
  imsgAvailable: boolean;
  intervalMinutes: number;
  watchCount: number;
  watchedOfferIds?: string[];
  lastCheckAt?: string | null;
  lastSentAt?: string | null;
  lastError?: string | null;
  error?: string;
  autoTestSent?: boolean;
  testSent?: boolean;
  activeRecipientId?: string | null;
  recipients?: AlertRecipient[];
  totalWatchCount?: number;
};
type AlertRecipient = { id: string; masked: string; watchCount: number };
type FavoriteWatch = {
  id: string;
  historyId?: string;
  clientOfferId: string;
  origin: string;
  destination: string;
  date: string;
  provider: string;
  segments: Array<{ flightNo: string; departTime: string; arriveTime: string; from: { city: string; code: string }; to: { city: string; code: string } }>;
  lastPrice: number;
  totalMinutes: number;
  transferMinutes?: number | null;
  createdAt: string;
  removedAt?: string;
  recipientId?: string;
};
type FavoriteFolder = { recipientId?: string | null; favorites: FavoriteWatch[]; history: FavoriteWatch[] };

function localDate(offset = 2) {
  const date = new Date();
  date.setDate(date.getDate() + offset);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function formatDuration(minutes: number) {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return `${hours}小时${rest ? `${rest}分` : ""}`;
}

function priceChecks(offer: Offer) {
  return (offer.evidence || [])
    .filter((item) => item.provider === offer.provider || item.source.startsWith(`${offer.provider}-`))
    .slice(0, 2);
}

function evidenceKey(evidence: PriceEvidence) {
  return evidence.checkId || evidence.source;
}

function activePriceCheck(offer: Offer, selections: Record<string, string>) {
  const checks = priceChecks(offer);
  return checks.find((item) => evidenceKey(item) === selections[offer.id]) || checks.at(-1);
}

export function FlightFinder() {
  const [origin, setOrigin] = useState("PEK");
  const [transfer, setTransfer] = useState("XIY");
  const [destination, setDestination] = useState("CTU");
  const [originPlace, setOriginPlace] = useState("北京");
  const [transferPlace, setTransferPlace] = useState("西安");
  const [destinationPlace, setDestinationPlace] = useState("成都");
  const [date, setDate] = useState(localDate());
  const [offers, setOffers] = useState<Offer[]>([]);
  const [mode, setMode] = useState<"verified" | "unavailable">("unavailable");
  const [searchedAt, setSearchedAt] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [favorites, setFavorites] = useState<string[]>(() => {
    if (typeof window === "undefined") return [];
    try {
      return JSON.parse(localStorage.getItem("flight-favorites") || "[]");
    } catch {
      return [];
    }
  });
  const [selectionTarget, setSelectionTarget] = useState<SelectionTarget>("origin");
  const [pickerMode, setPickerMode] = useState<PickerMode>("city");
  const [pickerQuery, setPickerQuery] = useState("");
  const [selectedChecks, setSelectedChecks] = useState<Record<string, string>>({});
  const [showCrossDay, setShowCrossDay] = useState(false);
  const [ctripConnected, setCtripConnected] = useState(false);
  const [otaStatus, setOtaStatus] = useState<OtaStatus>({});
  const [otaBusy, setOtaBusy] = useState<OtaProviderKey | "">("");
  const [otaFeedback, setOtaFeedback] = useState("");
  const [shuttingDown, setShuttingDown] = useState(false);
  const [purchaseAssistId, setPurchaseAssistId] = useState("");
  const [copiedOfferId, setCopiedOfferId] = useState("");
  const [throughOnly, setThroughOnly] = useState(false);
  const [appliedThroughOnly, setAppliedThroughOnly] = useState(false);
  const [searchContext, setSearchContext] = useState<SearchContext | null>(null);
  const [alertStatus, setAlertStatus] = useState<AlertStatus | null>(null);
  const [activeRecipientId, setActiveRecipientId] = useState("");
  const [alertPanelOpen, setAlertPanelOpen] = useState(false);
  const [alertRecipient, setAlertRecipient] = useState("");
  const [alertEnabled, setAlertEnabled] = useState(false);
  const [alertBusy, setAlertBusy] = useState(false);
  const [alertFeedback, setAlertFeedback] = useState("");
  const [favoriteFolder, setFavoriteFolder] = useState<FavoriteFolder>({ favorites: [], history: [] });
  const [favoriteFolderOpen, setFavoriteFolderOpen] = useState(false);
  const [favoriteSelection, setFavoriteSelection] = useState<string[]>([]);
  const [favoriteFolderBusy, setFavoriteFolderBusy] = useState(false);
  const [favoriteFolderFeedback, setFavoriteFolderFeedback] = useState("");
  const [favoriteTargets, setFavoriteTargets] = useState<Record<string, string>>({});

  const refreshFavoriteFolder = useCallback(async (recipientId?: string) => {
    try {
      const query = recipientId ? `?recipientId=${encodeURIComponent(recipientId)}` : "";
      const response = await fetch(`/api/alerts/favorites${query}`, { cache: "no-store" });
      if (!response.ok) return;
      applyFavoriteFolder(await response.json() as FavoriteFolder);
    } catch {
      // The online preview intentionally has no device-local favorites service.
    }
  }, []);

  useEffect(() => {
    fetch("/api/ota", { cache: "no-store" })
      .then((response) => response.json())
      .then((status: OtaStatus) => {
        setOtaStatus(status);
        setCtripConnected(Boolean(status.providers?.ctrip?.connected));
      })
      .catch(() => {
        setOtaStatus({ available: false });
        setCtripConnected(false);
      });
    fetch("/api/alerts/status", { cache: "no-store" })
      .then((response) => response.json())
      .then((status: AlertStatus) => {
        setAlertStatus(status);
        setAlertEnabled(Boolean(status.enabled));
        setActiveRecipientId(status.activeRecipientId || "");
      })
      .catch(() => setAlertStatus(null));
    void refreshFavoriteFolder();
  }, [refreshFavoriteFolder]);

  const sortedOffers = useMemo(() => {
    const prices = offers.map((offer) => activePriceCheck(offer, selectedChecks)?.price ?? offer.price);
    const durations = offers.map((offer) => offer.totalMinutes);
    const stops = offers.map((offer) => Math.max(0, offer.segments.length - 1));
    const normalized = (value: number, values: number[]) => {
      const low = Math.min(...values);
      const high = Math.max(...values);
      return high === low ? 0 : (value - low) / (high - low);
    };
    const score = (offer: Offer) => {
      const price = activePriceCheck(offer, selectedChecks)?.price ?? offer.price;
      return normalized(price, prices) * 0.55
        + normalized(offer.totalMinutes, durations) * 0.35
        + normalized(Math.max(0, offer.segments.length - 1), stops) * 0.10;
    };
    return [...offers].sort((a, b) => {
      const favoriteDelta = Number(favorites.includes(b.id)) - Number(favorites.includes(a.id));
      const aPrice = activePriceCheck(a, selectedChecks)?.price ?? a.price;
      const bPrice = activePriceCheck(b, selectedChecks)?.price ?? b.price;
      return favoriteDelta || score(a) - score(b) || aPrice - bPrice || a.totalMinutes - b.totalMinutes;
    });
  }, [offers, favorites, selectedChecks]);
  const crossDayOfferCount = sortedOffers.filter((offer) => offer.crossDay).length;
  const visibleOffers = showCrossDay ? sortedOffers : sortedOffers.filter((offer) => !offer.crossDay);

  const filteredCityOptions = useMemo(() => {
    const query = pickerQuery.trim().toLowerCase();
    if (!query) return cityOptions.filter((item) => item.level === "city");
    return cityOptions.filter((item) => {
      const nearbyAirports = item.nearby.map(({ code }) => cityMap[code]).filter(Boolean);
      return `${item.city}${item.fullName}${item.province}${nearbyAirports.map((airport) => `${airport.code}${airport.airport}${airport.englishName}`).join("")}`
        .toLowerCase()
        .includes(query);
    }).slice(0, 160);
  }, [pickerQuery]);

  const filteredAirports = useMemo(() => {
    const query = pickerQuery.trim().toLowerCase();
    if (!query) return airports;
    return airports.filter((airport) =>
      `${airport.city}${airport.airport}${airport.englishName}${airport.code}`.toLowerCase().includes(query),
    );
  }, [pickerQuery]);

  async function search(event?: FormEvent) {
    event?.preventDefault();
    setError("");
    if (new Set([origin, destination, ...(transfer ? [transfer] : [])]).size !== (transfer ? 3 : 2)) {
      setError("出发地、转机地和到达地不能重复，请重新选择。 ");
      return;
    }
    setOffers([]);
    setSelectedChecks({});
    setShowCrossDay(false);
    setPurchaseAssistId("");
    setCopiedOfferId("");
    setMode("unavailable");
    setLoading(true);
    try {
      const context: SearchContext = {
        origin,
        originCity: cityMap[origin].city,
        destination,
        destinationCity: cityMap[destination].city,
        transfer: transfer || null,
        transferCity: transfer ? transferPlace : null,
        date,
        throughOnly,
      };
      const query = new URLSearchParams({ origin, destination, date });
      if (transfer) {
        query.set("transfer", transfer);
        query.set("transfer_city", transferPlace);
      }
      if (throughOnly) query.set("through_only", "true");
      const response = await fetch(`/api/flights?${query.toString()}`, { cache: "no-store" });
      const data = (await response.json()) as SearchResponse & { error?: string };
      if (!response.ok) throw new Error(data.error || "查询失败，请稍后再试");
      setOffers(data.offers);
      setMode(data.mode);
      setSearchedAt(data.searchedAt);
      setAppliedThroughOnly(throughOnly);
      setSearchContext(context);
      for (const offer of data.offers.filter((item) => favorites.includes(item.id))) {
        void registerFavorite(offer, context, offer.price);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "查询失败，请稍后再试");
    } finally {
      setLoading(false);
    }
  }

  async function openOtaLogin(provider: OtaProviderKey) {
    setOtaBusy(provider);
    setOtaFeedback("");
    try {
      const response = await fetch("/api/ota", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ provider }),
      });
      const data = await response.json() as { error?: string; label?: string };
      if (!response.ok) throw new Error(data.error || "登录窗口打开失败");
      setOtaFeedback(`${data.label || "平台"}隔离登录窗口已打开`);
      setOtaStatus((current) => ({
        ...current,
        available: true,
        providers: {
          ...current.providers,
          [provider]: { label: data.label || provider, connected: true },
        },
      }));
      if (provider === "ctrip") setCtripConnected(true);
    } catch (reason) {
      setOtaFeedback(reason instanceof Error ? reason.message : "登录窗口打开失败");
    } finally {
      setOtaBusy("");
    }
  }

  async function stopFeimi() {
    if (!window.confirm("将退出飞觅并停止网页、实时抓价、价格提醒和隔离登录窗口。确定退出吗？")) return;
    setShuttingDown(true);
    try {
      const response = await fetch("/api/system/stop", { method: "POST" });
      const data = await response.json() as { error?: string; message?: string };
      if (!response.ok) throw new Error(data.error || "关闭服务失败");
      setOtaFeedback(data.message || "飞觅正在退出");
      // This page is opened by the user's normal browser, which may reject
      // window.close().  Navigating away still gives a clear, graceful exit.
      window.setTimeout(() => {
        window.location.replace("about:blank");
        window.close();
      }, 150);
    } catch (reason) {
      setOtaFeedback(reason instanceof Error ? reason.message : "关闭服务失败");
      setShuttingDown(false);
    }
  }

  async function registerFavorite(offer: Offer, context: SearchContext, price: number) {
    try {
      const response = await fetch("/api/alerts/watch", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          clientOfferId: offer.id,
          ...context,
          provider: offer.provider,
          price,
          segments: offer.segments.map((segment) => ({
            flightNo: segment.flightNo,
            departTime: segment.departTime,
            arriveTime: segment.arriveTime,
            from: { code: segment.from.code, city: segment.from.city },
            to: { code: segment.to.code, city: segment.to.city },
          })),
          purchaseUrl: offer.purchaseUrl,
          totalMinutes: offer.totalMinutes,
          transferMinutes: offer.transferMinutes,
          recipientId: activeRecipientId || undefined,
        }),
      });
      const status = await response.json() as AlertStatus;
      if (response.ok) {
        setAlertStatus(status);
        void refreshFavoriteFolder(activeRecipientId);
      }
    } catch {
      // The desktop alert service is optional; local favorite pinning still works.
    }
  }

  function toggleFavorite(offer: Offer) {
    const adding = !favorites.includes(offer.id);
    if (adding && !activeRecipientId) {
      setAlertPanelOpen(true);
      setAlertFeedback("请先添加并选择一个 iMessage 提醒号码，再收藏机票。");
      return;
    }
    setFavorites((current) => {
      const next = current.includes(offer.id) ? current.filter((item) => item !== offer.id) : [...current, offer.id];
      localStorage.setItem("flight-favorites", JSON.stringify(next));
      return next;
    });
    if (adding && searchContext) {
      const selectedPrice = activePriceCheck(offer, selectedChecks)?.price ?? offer.price;
      void registerFavorite(offer, searchContext, selectedPrice);
    } else if (!adding) {
      const recipientQuery = activeRecipientId ? `&recipientId=${encodeURIComponent(activeRecipientId)}` : "";
      void fetch(`/api/alerts/watch?id=${encodeURIComponent(offer.id)}${recipientQuery}`, { method: "DELETE" })
        .then((response) => response.json())
        .then((status: AlertStatus) => {
          setAlertStatus(status);
          void refreshFavoriteFolder(activeRecipientId);
        })
        .catch(() => undefined);
    }
  }

  function applyFavoriteFolder(folder: FavoriteFolder) {
    setFavoriteFolder(folder);
    const activeIds = folder.favorites.map((item) => item.clientOfferId);
    setFavorites(activeIds);
    localStorage.setItem("flight-favorites", JSON.stringify(activeIds));
    setFavoriteSelection((current) => current.filter((id) => activeIds.includes(id)));
  }

  async function cancelSelectedFavorites() {
    if (!favoriteSelection.length) return;
    setFavoriteFolderBusy(true);
    setFavoriteFolderFeedback("");
    try {
      await Promise.all(favoriteSelection.map(async (offerId) => {
        const recipientQuery = activeRecipientId ? `&recipientId=${encodeURIComponent(activeRecipientId)}` : "";
        const response = await fetch(`/api/alerts/watch?id=${encodeURIComponent(offerId)}${recipientQuery}`, { method: "DELETE" });
        if (!response.ok) throw new Error("取消收藏失败");
      }));
      await refreshFavoriteFolder(activeRecipientId);
      setFavoriteFolderFeedback(`已取消 ${favoriteSelection.length} 个收藏，记录已移入收藏历史。`);
    } catch (reason) {
      setFavoriteFolderFeedback(reason instanceof Error ? reason.message : "取消收藏失败");
    } finally {
      setFavoriteFolderBusy(false);
    }
  }

  async function deleteFavoriteHistory(historyId: string) {
    setFavoriteFolderBusy(true);
    setFavoriteFolderFeedback("");
    try {
      const response = await fetch(`/api/alerts/history/${encodeURIComponent(historyId)}`, { method: "DELETE" });
      const folder = await response.json() as FavoriteFolder & { error?: string };
      if (!response.ok) throw new Error(folder.error || "删除历史失败");
      applyFavoriteFolder(folder);
    } catch (reason) {
      setFavoriteFolderFeedback(reason instanceof Error ? reason.message : "删除历史失败");
    } finally {
      setFavoriteFolderBusy(false);
    }
  }

  function applyAlertStatus(status: AlertStatus) {
    setAlertStatus(status);
    setAlertEnabled(Boolean(status.enabled));
    setActiveRecipientId(status.activeRecipientId || "");
  }

  async function addAlertRecipient() {
    const recipient = alertRecipient.trim();
    if (!recipient) return;
    setAlertBusy(true);
    setAlertFeedback("");
    try {
      const response = await fetch("/api/alerts/recipients", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ recipient }),
      });
      const status = await response.json() as AlertStatus;
      if (!response.ok) throw new Error(status.error || "添加提醒号码失败");
      applyAlertStatus(status);
      setAlertRecipient("");
      await refreshFavoriteFolder(status.activeRecipientId || undefined);
      setAlertFeedback(status.testSent ? "号码已添加，测试 iMessage 已发送" : "号码已存在，已切换到该号码");
    } catch (reason) {
      setAlertFeedback(reason instanceof Error ? reason.message : "添加提醒号码失败");
    } finally {
      setAlertBusy(false);
    }
  }

  async function selectAlertRecipient(recipientId: string) {
    setAlertBusy(true);
    setAlertFeedback("");
    try {
      const response = await fetch("/api/alerts/status", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ enabled: alertEnabled, activeRecipientId: recipientId }),
      });
      const status = await response.json() as AlertStatus;
      if (!response.ok) throw new Error(status.error || "切换号码失败");
      applyAlertStatus(status);
      await refreshFavoriteFolder(recipientId);
      setFavoriteSelection([]);
    } catch (reason) {
      setAlertFeedback(reason instanceof Error ? reason.message : "切换号码失败");
    } finally {
      setAlertBusy(false);
    }
  }

  async function removeAlertRecipient(recipientId: string) {
    const recipient = alertStatus?.recipients?.find((item) => item.id === recipientId);
    const target = alertStatus?.recipients?.find((item) => item.id !== recipientId);
    const moveNote = recipient?.watchCount ? `该号码的 ${recipient.watchCount} 个收藏将移动到 ${target?.masked || "其他号码"}。` : "";
    if (!window.confirm(`确定移除 ${recipient?.masked || "此号码"}？${moveNote}`)) return;
    setAlertBusy(true);
    setAlertFeedback("");
    try {
      const response = await fetch(`/api/alerts/recipients/${encodeURIComponent(recipientId)}`, {
        method: "DELETE",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ ...(target ? { moveToRecipientId: target.id } : {}) }),
      });
      const status = await response.json() as AlertStatus;
      if (!response.ok) throw new Error(status.error || "移除号码失败");
      applyAlertStatus(status);
      await refreshFavoriteFolder(status.activeRecipientId || undefined);
      setAlertFeedback(target && recipient?.watchCount ? `号码已移除，收藏已移动到 ${target.masked}` : "号码已移除");
    } catch (reason) {
      setAlertFeedback(reason instanceof Error ? reason.message : "移除号码失败");
    } finally {
      setAlertBusy(false);
    }
  }

  async function moveFavoriteToRecipient(offerId: string, recipientId: string) {
    setFavoriteFolderBusy(true);
    setFavoriteFolderFeedback("");
    try {
      const response = await fetch(`/api/alerts/watch/${encodeURIComponent(offerId)}/recipient`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ recipientId, sourceRecipientId: activeRecipientId }),
      });
      const status = await response.json() as AlertStatus;
      if (!response.ok) throw new Error(status.error || "移动收藏失败");
      setAlertStatus(status);
      await refreshFavoriteFolder(activeRecipientId);
      setFavoriteFolderFeedback("收藏机票已移动到所选提醒号码。");
    } catch (reason) {
      setFavoriteFolderFeedback(reason instanceof Error ? reason.message : "移动收藏失败");
    } finally {
      setFavoriteFolderBusy(false);
    }
  }

  async function copyFavoriteToRecipient(offerId: string, targetRecipientId: string) {
    if (!activeRecipientId || !targetRecipientId || targetRecipientId === activeRecipientId) return;
    setFavoriteFolderBusy(true);
    setFavoriteFolderFeedback("");
    try {
      const response = await fetch(`/api/alerts/watch/${encodeURIComponent(offerId)}/copy`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ sourceRecipientId: activeRecipientId, targetRecipientId }),
      });
      const result = await response.json() as AlertStatus & { copied?: boolean };
      if (!response.ok) throw new Error(result.error || "复制收藏失败");
      setAlertStatus(result);
      const target = result.recipients?.find((recipient) => recipient.id === targetRecipientId);
      setFavoriteFolderFeedback(result.copied
        ? `已复制到 ${target?.masked || "所选号码"}，当前号码的收藏继续保留。`
        : `${target?.masked || "所选号码"} 已收藏该航班，无需重复复制。`);
    } catch (reason) {
      setFavoriteFolderFeedback(reason instanceof Error ? reason.message : "复制收藏失败");
    } finally {
      setFavoriteFolderBusy(false);
    }
  }

  async function saveAlertSettings() {
    setAlertBusy(true);
    setAlertFeedback("");
    try {
      const response = await fetch("/api/alerts/status", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          enabled: alertEnabled,
          ...(activeRecipientId ? { activeRecipientId } : {}),
        }),
      });
      const status = await response.json() as AlertStatus;
      if (!response.ok) throw new Error(status.error || "保存失败");
      applyAlertStatus(status);
      setAlertFeedback(alertEnabled
        ? status.autoTestSent
          ? "已启用并自动发送测试 iMessage，请检查“信息”应用"
          : "提醒已保持启用，每 30 分钟检查一次"
        : "价格提醒已暂停");
    } catch (reason) {
      setAlertFeedback(reason instanceof Error ? reason.message : "保存失败");
    } finally {
      setAlertBusy(false);
    }
  }

  async function testAlertDelivery() {
    setAlertBusy(true);
    setAlertFeedback("");
    try {
      const response = await fetch("/api/alerts/test", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ ...(activeRecipientId ? { recipientId: activeRecipientId } : {}) }),
      });
      const status = await response.json() as AlertStatus;
      if (!response.ok) throw new Error(status.error || "测试信息发送失败");
      setAlertStatus(status);
      setAlertFeedback("测试 iMessage 已发送，请检查‘信息’应用");
    } catch (reason) {
      setAlertFeedback(reason instanceof Error ? reason.message : "测试信息发送失败");
    } finally {
      setAlertBusy(false);
    }
  }

  async function checkAlertsNow() {
    setAlertBusy(true);
    setAlertFeedback("");
    try {
      const response = await fetch("/api/alerts/check", { method: "POST" });
      const status = await response.json() as AlertStatus & { checked?: number; sent?: number };
      if (!response.ok) throw new Error(status.error || "检查失败");
      setAlertStatus(status);
      setAlertFeedback(`检查完成：核对 ${status.checked || 0} 个收藏，发送 ${status.sent || 0} 条提醒`);
    } catch (reason) {
      setAlertFeedback(reason instanceof Error ? reason.message : "检查失败");
    } finally {
      setAlertBusy(false);
    }
  }

  async function copyBookingReference(offer: Offer) {
    const reference = buildBookingReference(offer.segments, date, offer.totalMinutes, offer.transferMinutes);
    try {
      await navigator.clipboard.writeText(reference);
      setCopiedOfferId(offer.id);
      window.setTimeout(() => setCopiedOfferId((current) => current === offer.id ? "" : current), 2200);
    } catch {
      setCopiedOfferId("");
    }
  }

  function chooseAirport(code: string, placeName?: string) {
    setError("");
    setPickerQuery("");
    if (selectionTarget === "origin") {
      setOrigin(code);
      setOriginPlace(placeName || cityMap[code]?.city || "");
      setSelectionTarget("transfer");
    } else if (selectionTarget === "transfer") {
      setTransfer(code);
      setTransferPlace(code ? placeName || cityMap[code]?.city || "" : "");
      setSelectionTarget("destination");
    } else {
      setDestination(code);
      setDestinationPlace(placeName || cityMap[code]?.city || "");
    }
  }

  function isUnavailable(code: string) {
    if (selectionTarget === "origin") return code === transfer || code === destination;
    if (selectionTarget === "transfer") return code === origin || code === destination;
    return code === origin || code === transfer;
  }

  function recommendedAirport(option: CityOption) {
    return option.nearby.find(({ code }) => !isUnavailable(code));
  }

  function chooseCity(option: CityOption) {
    const recommended = recommendedAirport(option);
    if (recommended) chooseAirport(recommended.code, option.city);
  }

  const selectedOrigin = { ...cityMap[origin], city: originPlace };
  const selectedTransfer = transfer ? { ...cityMap[transfer], city: transferPlace } : undefined;
  const selectedDestination = { ...cityMap[destination], city: destinationPlace };
  const targetLabels: Record<SelectionTarget, string> = {
    origin: "出发地",
    transfer: "转机地",
    destination: "到达地",
  };

  return (
    <main>
      <header className="topbar">
        <a className="brand" href="#top" aria-label="飞觅首页">
          <span className="brand-mark">↗</span>
          <span>飞觅</span>
        </a>
        <nav aria-label="页面导航">
          <a href="#search">查机票</a>
          <a href="#results">低价结果</a>
        </nav>
        <div className="ota-logins" aria-label="平台登录入口">
          {(["ctrip", "qunar", "meituan"] as OtaProviderKey[]).map((provider) => {
            const label = otaStatus.providers?.[provider]?.label || ({ ctrip: "携程", qunar: "去哪儿", meituan: "美团" } as const)[provider];
            const connected = otaStatus.providers?.[provider]?.connected;
            return <button key={provider} type="button" className={connected ? "connected" : ""} onClick={() => openOtaLogin(provider)} disabled={otaBusy === provider} title={`打开${label}隔离登录窗口`}><i />{otaBusy === provider ? "打开中" : `${label}登录`}</button>;
          })}
          {otaFeedback && <span role="status">{otaFeedback}</span>}
        </div>
        <button className="shutdown-button" type="button" onClick={stopFeimi} disabled={shuttingDown} title="退出飞觅并停止全部本地服务">
          {shuttingDown ? "正在退出" : "退出飞觅"}
        </button>
        <div className="live-pill"><span /> {ctripConnected || otaStatus.providers?.qunar?.connected ? "携程 + 去哪儿实时" : "双价人工复核"}</div>
      </header>

      <section className="hero" id="top">
        <div className="hero-copy">
          <p className="eyebrow">国内机票 · 多站比价</p>
          <h1>少花一点，<br /><em>飞远一点。</em></h1>
          <p className="hero-subtitle">选择城市即可自动匹配最近机场。普通转机至少预留 2 小时；平台明确标记且含航变保障的通程航班，可按航司联程时间展示，最低 90 分钟。</p>
          <div className="trust-row">
            <span>✓ 两次价格都展示</span>
            <span>✓ 无直飞自动转机</span>
            <span>✓ 总行程不超过 16 小时</span>
            <span>✓ 价格 55% · 时长 35% · 转机 10%</span>
            <span>✓ 普通转机 ≥ 2h · 通程保障 ≥ 90min</span>
            <span>✓ 关注航班置顶</span>
          </div>
        </div>

        <form className="search-card" id="search" onSubmit={search}>
          <div className="card-heading">
            <div>
              <span className="step">01</span>
              <h2>规划这段旅程</h2>
            </div>
            <span className="one-way">单程</span>
          </div>

          <div className="route-fieldset">
            <button className={`route-choice ${selectionTarget === "origin" ? "active" : ""}`} type="button" onClick={() => setSelectionTarget("origin")} aria-pressed={selectionTarget === "origin"} aria-label={`选择出发地，当前${selectedOrigin.city}`}>
              <span>出发地</span>
              <strong>{selectedOrigin.city} <b>{selectedOrigin.code}</b></strong>
              <small>{selectedOrigin.airport}机场</small>
            </button>
            <div className="route-line" aria-hidden="true"><span>✈</span></div>
            <button className={`route-choice ${selectionTarget === "transfer" ? "active" : ""}`} type="button" onClick={() => setSelectionTarget("transfer")} aria-pressed={selectionTarget === "transfer"} aria-label={`选择转机地，当前${selectedTransfer?.city || "不指定"}`}>
              <span>转机地 <b>可选</b></span>
              <strong>{selectedTransfer ? <>{selectedTransfer.city} <b>{selectedTransfer.code}</b></> : "不指定"}</strong>
              <small>{transfer ? "普通转机至少预留 2 小时" : "直飞无票则自动转机"}</small>
            </button>
            <div className="route-line" aria-hidden="true"><span>✈</span></div>
            <button className={`route-choice ${selectionTarget === "destination" ? "active" : ""}`} type="button" onClick={() => setSelectionTarget("destination")} aria-pressed={selectionTarget === "destination"} aria-label={`选择到达地，当前${selectedDestination.city}`}>
              <span>到达地</span>
              <strong>{selectedDestination.city} <b>{selectedDestination.code}</b></strong>
              <small>{selectedDestination.airport}机场</small>
            </button>
          </div>

          <div className="airport-panel">
            <div className="airport-panel-heading">
              <div>
                <strong>选择{targetLabels[selectionTarget]}</strong>
                <span>先选城市，自动匹配最近可用机场 · 覆盖 {airports.length} 个通航机场</span>
              </div>
              <label className="airport-search">
                <span aria-hidden="true">⌕</span>
                <input value={pickerQuery} onChange={(event) => setPickerQuery(event.target.value)} placeholder={pickerMode === "city" ? "搜索城市或区县" : "搜索机场或三字码"} aria-label={pickerMode === "city" ? "搜索城市" : "搜索机场"} />
              </label>
            </div>
            <div className="picker-tabs" role="tablist" aria-label="地点选择方式">
              <button className={pickerMode === "city" ? "active" : ""} type="button" onClick={() => { setPickerMode("city"); setPickerQuery(""); }} role="tab" aria-selected={pickerMode === "city"}>按城市智能匹配 <small>{cityOptions.length} 城市/区县</small></button>
              <button className={pickerMode === "airport" ? "active" : ""} type="button" onClick={() => { setPickerMode("airport"); setPickerQuery(""); }} role="tab" aria-selected={pickerMode === "airport"}>全部机场 <small>{airports.length} 个</small></button>
            </div>
            <div className={`airport-grid ${pickerMode === "city" ? "city-grid" : ""}`} role="listbox" aria-label={`平铺选择${targetLabels[selectionTarget]}`}>
              {selectionTarget === "transfer" && (
                <button className={`airport-tile no-transfer ${transfer === "" ? "selected" : ""}`} type="button" onClick={() => chooseAirport("")} role="option" aria-selected={transfer === ""}>
                  <strong>不指定转机</strong><span>直飞优先 · 自动转机</span><small>AUTO</small>
                </button>
              )}
              {pickerMode === "city" ? filteredCityOptions.map((option) => {
                const recommended = recommendedAirport(option);
                const airport = recommended ? cityMap[recommended.code] : undefined;
                const selectedCode = selectionTarget === "origin" ? origin : selectionTarget === "transfer" ? transfer : destination;
                const selected = recommended?.code === selectedCode;
                return (
                  <button className={`airport-tile city-tile ${selected ? "selected" : ""}`} key={option.id} type="button" onClick={() => chooseCity(option)} disabled={!recommended} role="option" aria-selected={selected} aria-label={`${option.city}，自动匹配${airport?.airport || "最近"}机场`}>
                    <strong>{option.city}</strong>
                    <span>{option.province} · {airport?.airport || "暂无可用机场"}</span>
                    <small>{recommended?.code || "—"}</small>
                    {recommended && <i>距市中心约 {recommended.distanceKm} km</i>}
                  </button>
                );
              }) : filteredAirports.map((airport) => {
                const selected = selectionTarget === "origin" ? origin === airport.code : selectionTarget === "transfer" ? transfer === airport.code : destination === airport.code;
                const unavailable = isUnavailable(airport.code);
                return (
                  <button className={`airport-tile ${selected ? "selected" : ""}`} key={airport.code} type="button" onClick={() => chooseAirport(airport.code)} disabled={unavailable} role="option" aria-selected={selected}>
                    <strong>{airport.city}</strong><span>{airport.airport}</span><small>{airport.code}</small>
                  </button>
                );
              })}
              {pickerMode === "city" && !filteredCityOptions.length && <p className="airport-empty">没有匹配的城市，试试完整城市名或区县名。</p>}
              {pickerMode === "airport" && !filteredAirports.length && <p className="airport-empty">没有匹配的机场，试试机场名或三字代码。</p>}
            </div>
          </div>

          <div className="search-footer">
            <label className="date-control">
              <span>出发日期</span>
              <input type="date" value={date} min={localDate(0)} onChange={(event) => setDate(event.target.value)} required />
            </label>
            <label className={`through-filter ${throughOnly ? "selected" : ""}`}>
              <input type="checkbox" checked={throughOnly} onChange={(event) => setThroughOnly(event.target.checked)} />
              <span aria-hidden="true"><i /></span>
              <p><strong>仅看通程航班</strong><small>一次支付·行李直挂·航变保障·衔接 ≥ 90 分钟</small></p>
            </label>
            <div className="safety-note"><span>2h</span><p><strong>安心转机保护</strong><br />普通转机不足 2 小时不展示；明确通程保障最低 90 分钟</p></div>
            <button className="search-button" type="submit" disabled={loading}>
              {loading ? <><i className="spinner" />正在搜索全网</> : <>搜索最低价 <span>→</span></>}
            </button>
          </div>
          {error && <p className="form-error" role="alert">{error}</p>}
        </form>
      </section>

      <section className="results-section" id="results">
        <div className={`alert-center ${alertStatus?.enabled ? "active" : ""}`}>
          <div className="alert-summary">
            <span className="alert-icon" aria-hidden="true">✦</span>
            <div>
              <strong>收藏机票价格提醒</strong>
              <small>
                {alertStatus?.available === false
                  ? "桌面版专属 · iMessage 通知"
                  : alertStatus?.enabled
                    ? `运行中 · 每 ${alertStatus.intervalMinutes} 分钟检查 · ${alertStatus.watchCount} 个收藏`
                    : `每 30 分钟检查 · 价格上涨或下降才通知`}
              </small>
            </div>
            <span className="alert-state">
              {alertStatus?.available === false ? "仅桌面版" : alertStatus?.enabled ? "监控中" : "未启用"}
            </span>
            <button type="button" onClick={() => setAlertPanelOpen((current) => !current)} aria-expanded={alertPanelOpen}>
              {alertPanelOpen ? "收起" : "通知设置"}
            </button>
            <button type="button" onClick={() => setFavoriteFolderOpen((current) => !current)} aria-expanded={favoriteFolderOpen}>
              收藏夹 {favoriteFolder.favorites.length}
            </button>
          </div>
          {alertPanelOpen && (
            <div className="alert-settings">
              {alertStatus?.available === false ? (
                <p>在线页面无法访问这台 Mac 的“信息”应用。请从桌面的“飞觅机票”打开后配置。</p>
              ) : (
                <>
                  <div className="recipient-manager">
                    <span>提醒号码与对应收藏夹</span>
                    <div className="recipient-tabs">
                      {(alertStatus?.recipients || []).map((recipient) => (
                        <div className={recipient.id === activeRecipientId ? "selected" : ""} key={recipient.id}>
                          <button type="button" onClick={() => void selectAlertRecipient(recipient.id)} disabled={alertBusy}>{recipient.masked}<small>{recipient.watchCount} 个收藏</small></button>
                          <button type="button" aria-label={`移除提醒号码 ${recipient.masked}`} onClick={() => void removeAlertRecipient(recipient.id)} disabled={alertBusy}>×</button>
                        </div>
                      ))}
                    </div>
                    <label className="alert-recipient-add">
                      <input value={alertRecipient} onChange={(event) => setAlertRecipient(event.target.value)} placeholder="+86 手机号或 Apple ID 邮箱" autoComplete="off" inputMode="email" />
                      <button type="button" onClick={addAlertRecipient} disabled={alertBusy || !alertRecipient.trim()}>添加并测试</button>
                    </label>
                    <small>每个号码拥有独立收藏夹；新增号码会立即发送测试信息。</small>
                  </div>
                  <label className={`alert-enable ${alertEnabled ? "selected" : ""}`}>
                    <input type="checkbox" checked={alertEnabled} onChange={(event) => setAlertEnabled(event.target.checked)} />
                    <span aria-hidden="true"><i /></span>
                    <p><strong>启用自动提醒</strong><small>只在价格发生变化时发送</small></p>
                  </label>
                  <div className="alert-actions">
                    <button type="button" onClick={saveAlertSettings} disabled={alertBusy}>保存设置</button>
                    <button type="button" onClick={testAlertDelivery} disabled={alertBusy || !alertStatus?.recipientConfigured || !alertStatus?.imsgAvailable}>发送测试信息</button>
                    <button type="button" onClick={checkAlertsNow} disabled={alertBusy || !alertStatus?.enabled}>立即检查</button>
                  </div>
                  <div className="alert-privacy">
                    <span>{alertStatus?.imsgAvailable ? "✓ imsg 已连接" : "等待 imsg 安装"}</span>
                    <span>{alertStatus?.recipientConfigured ? `当前号码 ${alertStatus.recipientMasked}` : "尚未添加提醒号码"}</span>
                    <span>共 {alertStatus?.recipients?.length || 0} 个号码 · {alertStatus?.totalWatchCount || 0} 个收藏</span>
                    {alertStatus?.lastCheckAt && <span>上次检查 {new Date(alertStatus.lastCheckAt).toLocaleString("zh-CN")}</span>}
                  </div>
                  {alertFeedback && <p className="alert-feedback" role="status">{alertFeedback}</p>}
                  {alertStatus?.lastError && <p className="alert-error" role="alert">{alertStatus.lastError}</p>}
                </>
              )}
            </div>
          )}
          {favoriteFolderOpen && (
            <div className="favorite-folder">
              <div className="favorite-folder-heading">
                <div><strong>{alertStatus?.recipientMasked || "当前号码"} 的收藏机票</strong><small>可将单张机票复制或移动到其他号码；复制后两个号码会独立监控。</small></div>
                <div className="favorite-folder-actions">
                  <button type="button" onClick={() => setFavoriteSelection(favoriteFolder.favorites.map((item) => item.clientOfferId))} disabled={!favoriteFolder.favorites.length || favoriteFolderBusy}>全选</button>
                  <button type="button" onClick={() => setFavoriteSelection((current) => favoriteFolder.favorites.map((item) => item.clientOfferId).filter((id) => !current.includes(id)))} disabled={!favoriteFolder.favorites.length || favoriteFolderBusy}>反选</button>
                  <button className="cancel-favorites" type="button" onClick={cancelSelectedFavorites} disabled={!favoriteSelection.length || favoriteFolderBusy}>{favoriteFolderBusy ? "处理中" : `取消所选 ${favoriteSelection.length}`}</button>
                </div>
              </div>
              {favoriteFolder.favorites.length ? (
                <div className="favorite-list">
                  {favoriteFolder.favorites.map((item) => {
                    const otherRecipients = (alertStatus?.recipients || []).filter((recipient) => recipient.id !== activeRecipientId);
                    const selectedTarget = favoriteTargets[item.id] || otherRecipients[0]?.id || "";
                    return (
                    <div className="favorite-row" key={item.id}>
                      <input aria-label={`选择 ${item.segments.map((segment) => segment.flightNo).join("+")}`} type="checkbox" checked={favoriteSelection.includes(item.clientOfferId)} onChange={() => setFavoriteSelection((current) => current.includes(item.clientOfferId) ? current.filter((id) => id !== item.clientOfferId) : [...current, item.clientOfferId])} />
                      <div><strong>{item.segments[0]?.from.city} → {item.segments.at(-1)?.to.city}</strong><small>{item.date} · {item.provider} · {item.segments.map((segment) => segment.flightNo).join(" + ")}</small><small className="favorite-time">出发 {item.segments[0]?.departTime || "--:--"} · 到达 {item.segments.at(-1)?.arriveTime || "--:--"}</small></div>
                      <span>¥{item.lastPrice}</span>
                      {otherRecipients.length ? (
                        <div className="favorite-transfer-actions">
                          <select aria-label={`${item.segments.map((segment) => segment.flightNo).join("+")} 的目标提醒号码`} value={selectedTarget} onChange={(event) => setFavoriteTargets((current) => ({ ...current, [item.id]: event.target.value }))} disabled={favoriteFolderBusy}>
                            {otherRecipients.map((recipient) => <option key={recipient.id} value={recipient.id}>{recipient.masked}</option>)}
                          </select>
                          <button type="button" onClick={() => void copyFavoriteToRecipient(item.clientOfferId, selectedTarget)} disabled={favoriteFolderBusy || !selectedTarget}>复制</button>
                          <button type="button" onClick={() => void moveFavoriteToRecipient(item.clientOfferId, selectedTarget)} disabled={favoriteFolderBusy || !selectedTarget}>移动</button>
                        </div>
                      ) : <em>全程 {formatDuration(item.totalMinutes)}</em>}
                    </div>
                  );})}
                </div>
              ) : <p className="favorite-empty">还没有收藏机票。搜索结果中点击“关注价格”即可加入。</p>}
              <div className="favorite-history-heading"><strong>收藏历史</strong><span>{favoriteFolder.history.length} 条</span></div>
              {favoriteFolder.history.length ? (
                <div className="favorite-list history-list">
                  {favoriteFolder.history.map((item) => (
                    <div className="favorite-row history-row" key={item.historyId}>
                      <div><strong>{item.segments[0]?.from.city} → {item.segments.at(-1)?.to.city}</strong><small>{item.date} · {item.segments.map((segment) => segment.flightNo).join(" + ")} · {item.removedAt ? `取消于 ${new Date(item.removedAt).toLocaleDateString("zh-CN")}` : "已取消"}</small><small className="favorite-time">出发 {item.segments[0]?.departTime || "--:--"} · 到达 {item.segments.at(-1)?.arriveTime || "--:--"}</small></div>
                      <span>¥{item.lastPrice}</span>
                      <button type="button" onClick={() => item.historyId && void deleteFavoriteHistory(item.historyId)} disabled={favoriteFolderBusy}>删除记录</button>
                    </div>
                  ))}
                </div>
              ) : <p className="favorite-empty history-empty">取消收藏后的机票会保留在这里。</p>}
              {favoriteFolderFeedback && <p className="favorite-feedback" role="status">{favoriteFolderFeedback}</p>}
            </div>
          )}
        </div>
        <div className="results-heading">
          <div>
            <p className="eyebrow">智能比价结果</p>
            <h2>{offers.length ? `${selectedOrigin.city} → ${selectedDestination.city}` : "准备好后，开始搜索"}</h2>
          </div>
          {offers.length > 0 && (
            <div className="results-meta">
              <span className={`source-badge ${mode}`}>双价可选择</span>
              <span>{new Date(searchedAt).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })} 更新</span>
              <span>{visibleOffers.length}/{offers.length} 个方案 · {appliedThroughOnly ? "通程筛选" : "综合排序"}</span>
            </div>
          )}
        </div>

        {offers.length > 0 && crossDayOfferCount > 0 && (
          <div className="cross-day-control">
            <span>已{showCrossDay ? "展开" : "折叠"} {crossDayOfferCount} 个跨日方案</span>
            <button type="button" onClick={() => setShowCrossDay((current) => !current)}>{showCrossDay ? "收起跨日方案" : "展开查看"}</button>
          </div>
        )}

        {!offers.length && !loading ? (
          <div className="empty-state">
            <div className="empty-route"><span>PEK</span><i /><b>✈</b><i /><span>CTU</span></div>
            <h3>你的低价路线图还空着</h3>
            <p>选好城市与日期，几秒钟后即可比较航班、总时长与转机余量。</p>
            <button onClick={() => search()} type="button">用当前路线试试看</button>
          </div>
        ) : (
          <div className="offers-list" aria-live="polite">
            {visibleOffers.map((offer, index) => {
              const favorite = favorites.includes(offer.id);
              const checks = priceChecks(offer);
              const selectedCheck = activePriceCheck(offer, selectedChecks);
              const selectedPrice = selectedCheck?.price ?? offer.price;
              const selectedPurchaseUrl = selectedCheck?.url || offer.purchaseUrl;
              const priceDifference = checks.length === 2 ? Math.abs(checks[0].price - checks[1].price) : 0;
              const purchaseAssistOpen = purchaseAssistId === offer.id;
              return (
                <article className={`offer-card ${favorite ? "favorite" : ""}`} key={offer.id}>
                  <div className="rank-block">
                    <span>{favorite ? "已关注" : index === 0 ? "综合优选" : `方案 ${index + 1}`}</span>
                    <b>{offer.provider.slice(0, 1)}</b>
                    <small>{offer.provider}</small>
                  </div>
                  <div className="flight-main">
                    <div className="flight-topline">
                      <div><strong>{offer.segments[0].departTime}</strong><span>{offer.segments[0].from.city} {offer.segments[0].from.code}</span></div>
                      <div className="duration-track">
                        <span>全程 {formatDuration(offer.totalMinutes)}</span>
                        <i><b>✈</b></i>
                        <em>{offer.transferMinutes ? `${offer.segments[0].to.city}转机 ${formatDuration(offer.transferMinutes)}` : "直飞"}</em>
                      </div>
                      <div className="arrival"><strong>{offer.segments.at(-1)!.arriveTime}</strong><span>{offer.segments.at(-1)!.to.city} {offer.segments.at(-1)!.to.code}</span></div>
                    </div>
                    <div className="flight-details">
                      <span>{offer.segments.map((segment) => `${segment.airline} ${segment.flightNo}`).join(" + ")}</span>
                      {offer.evidence && <b>{offer.evidence.length} 次价格确认</b>}
                      {offer.crossDay && <b>跨日行程</b>}
                      {offer.tags.map((tag) => <b key={tag}>{tag}</b>)}
                    </div>
                  </div>
                  <div className="price-block">
                    <button className="favorite-button" onClick={() => toggleFavorite(offer)} type="button" aria-pressed={favorite} aria-label={favorite ? "取消关注和价格监控" : "关注置顶并监控价格"}>
                      {favorite ? "★" : "☆"} {favorite ? "已监控" : "关注价格"}
                    </button>
                    <div className="price-review">
                      <small>{priceDifference ? `两次相差 ¥${priceDifference}` : "两次价格相同"}</small>
                      <div>
                        {checks.map((check, checkIndex) => {
                          const key = evidenceKey(check);
                          const selected = evidenceKey(selectedCheck || check) === key;
                          return (
                            <button className={selected ? "selected" : ""} type="button" key={key} onClick={() => setSelectedChecks((current) => ({ ...current, [offer.id]: key }))} aria-pressed={selected} title={check.source}>
                              <span>查询{checkIndex + 1}</span><b>¥{check.price}</b><em>{new Date(check.checkedAt).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</em>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                    <p><small>当前人工选择</small><span>¥</span><strong>{selectedPrice}</strong><em>起</em></p>
                    <button className="purchase-prep-button" type="button" onClick={() => setPurchaseAssistId((current) => current === offer.id ? "" : offer.id)} aria-expanded={purchaseAssistOpen}>
                      {purchaseAssistOpen ? "收起购票凭证" : `准备去${offer.provider}购票`} <span>{purchaseAssistOpen ? "↑" : "→"}</span>
                    </button>
                  </div>
                  {purchaseAssistOpen && (
                    <div className="purchase-assist">
                      <div className="purchase-assist-heading">
                        <div><span>{offer.provider}查找凭证</span><strong>请按航班号核对，不要只看价格</strong></div>
                        <small>{offer.provider}列表可能重新排序，票价也可能实时变化</small>
                      </div>
                      <div className="purchase-segments">
                        {offer.segments.map((segment, segmentIndex) => (
                          <div className="purchase-segment" key={`${segment.flightNo}-${segment.departTime}`}>
                            <span>第 {segmentIndex + 1} 程</span>
                            <strong>{segment.flightNo}</strong>
                            <b>{segment.airline}</b>
                            <p><time>{segment.departDate || date} {segment.departTime}</time><em>{segment.from.city} {segment.from.code}</em></p>
                            <i>→</i>
                            <p><time>{segment.arriveDate || segment.departDate || date} {segment.arriveTime}</time><em>{segment.to.city} {segment.to.code}</em></p>
                          </div>
                        ))}
                      </div>
                      <div className="purchase-assist-actions">
                        <p>{offer.transferMinutes ? `转机预留 ${formatDuration(offer.transferMinutes)} · ` : "直飞 · "}全程 {formatDuration(offer.totalMinutes)}</p>
                        <button type="button" onClick={() => copyBookingReference(offer)}>{copiedOfferId === offer.id ? "✓ 已复制" : "复制全部航班信息"}</button>
                        <a href={selectedPurchaseUrl} target="_blank" rel="noopener noreferrer">信息已记下，前往{offer.provider} <span>↗</span></a>
                      </div>
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        )}

        {offers.length > 0 && <p className="demo-disclaimer">仅保留总行程不超过 16 小时、转机不少于 2 小时的方案，跨日行程默认折叠且可手动展开。方案数量不做应用层截断，并按价格 55%、总时长 35%、转机次数 10% 综合排序；关注方案始终置顶。最终价格以出票页面为准。</p>}
      </section>

      <footer>
        <div className="brand footer-brand"><span className="brand-mark">↗</span><span>飞觅</span></div>
        <p>聪明地比较，从容地出发。</p>
        <span>票价仅供参考，请以出票页面为准</span>
      </footer>
    </main>
  );
}
