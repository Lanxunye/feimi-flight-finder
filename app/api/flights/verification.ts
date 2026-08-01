export type PriceEvidence = {
  source: string;
  provider?: string;
  checkId?: string;
  price: number;
  checkedAt: string;
  url?: string;
};

export type VerifiableOffer = {
  price: number;
  totalMinutes?: number;
  transferMinutes?: number | null;
  throughFlight?: boolean;
  evidence?: PriceEvidence[];
  [key: string]: unknown;
};

const MIN_PROTECTED_THROUGH_TRANSFER_MINUTES = 90;

export function verifiedEvidence(evidence: PriceEvidence[] | undefined) {
  if (!evidence?.length) return [];
  const valid = evidence.filter((item) =>
    item.source.trim() && Number.isFinite(item.price) && item.price > 0 && !Number.isNaN(Date.parse(item.checkedAt)),
  );
  const separateChecks = new Set(valid.map((item) => (item.checkId || item.source).trim().toLowerCase()));
  if (separateChecks.size < 2) return [];
  return valid;
}

export function filterVerifiedOffers<T extends VerifiableOffer>(offers: T[], minTransferMinutes = 120, throughOnly = false) {
  return offers.filter((offer) => {
    const evidence = verifiedEvidence(offer.evidence);
    if (evidence.length < 2) return false;
    if (offer.transferMinutes != null && offer.transferMinutes < minTransferMinutes) {
      if (offer.throughFlight !== true || offer.transferMinutes < MIN_PROTECTED_THROUGH_TRANSFER_MINUTES) return false;
    }
    if (offer.totalMinutes != null && offer.totalMinutes > 16 * 60) return false;
    if (throughOnly && offer.throughFlight !== true) return false;
    return evidence.some((item) => Math.abs(offer.price - item.price) < 0.01);
  });
}
