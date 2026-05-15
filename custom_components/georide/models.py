"""TypedDicts for the GeoRide API payloads.

These describe the shape of dicts returned by `api.GeoRideApiClient` —
they are NotRequired everywhere because the GeoRide API is not formally
documented and any field could be missing from a given response. The
integration code already handles missing keys defensively; these
TypedDicts make the contract readable for type checkers without making
runtime parsing stricter.
"""
from __future__ import annotations

from typing import NotRequired, TypedDict


class TrackerPayload(TypedDict, total=False):
    """Shape of one entry returned by `GET /user/trackers`.

    Every field is optional because the API may add, drop or rename
    keys on its side without notice. Keep the parsing logic in
    coordinator.py / sensor.py / binary_sensor.py defensive.
    """

    trackerId: int
    id: int
    trackerName: str
    model: str
    version: str
    softwareVersion: str
    odometer: int
    odometerUpdatedAt: str
    speed: float
    altitude: float
    latitude: float
    longitude: float
    lockedLatitude: float
    lockedLongitude: float
    lockedPositionId: int
    fixtime: str
    positionId: int
    internalBatteryVoltage: float
    externalBatteryVoltage: float
    batteryUpdatedAt: str
    isLocked: bool
    isStolen: bool
    isCrashed: bool
    hasTheftCaseOpened: bool
    moving: bool
    hasBeacon: bool
    hasOutdatedBeacons: bool
    isInEco: bool
    isInElectricMode: bool
    isOldSubscription: bool
    isOldTracker: bool
    isSecondGen: bool
    isUpToDate: bool
    isCalibrated: bool
    isDemo: bool
    canLock: bool
    canUnlock: bool
    canCheckSpeed: bool
    canSeePosition: bool
    canSeeStatistics: bool
    canShare: bool
    canUnshare: bool
    canSendBrokenDownSignal: bool
    canSendStolenSignal: bool
    crashDetectionDisabled: bool
    crashParkingEnabled: bool
    assistanceTheftActivated: bool
    eCallActivated: bool
    eCallCrashMode: str
    emergencyCallEnabled: bool
    friendCallEnabled: bool
    expires: str
    activationDate: str
    lastPaymentDate: str
    subscription: str
    subscriptionId: int
    businessModel: str
    status: str
    role: str
    review: int
    timezone: str
    vibrationLevel: int
    manualLock: bool
    autoLockFreezedTo: NotRequired[str | None]
    maintenanceModeUntil: NotRequired[str | None]
    bleScanDelay: int
    bleSoftwareVersion: int
    deviceButtonAction: str
    deviceButtonDelay: int
    giftCardId: NotRequired[int | None]
    giftCardMonths: NotRequired[int | None]
    giftCardExpires: NotRequired[str | None]


class TripPayload(TypedDict, total=False):
    """Shape of one trip returned by `GET /tracker/{id}/trips`."""

    id: int
    trackerId: int
    startTime: str
    endTime: str
    distance: int  # meters
    duration: int  # milliseconds
    averageSpeed: float
    maxSpeed: float
    averageAngle: float
    maxAngle: float
    maxLeftAngle: float
    maxRightAngle: float
    startLat: float
    startLon: float
    endLat: float
    endLon: float
    startAddress: str
    endAddress: str
    niceStartAddress: NotRequired[str | None]
    niceEndAddress: NotRequired[str | None]
    staticImage: str
    isFavorite: bool


class BeaconPayload(TypedDict, total=False):
    """Shape of one beacon returned by `GET /tracker/{id}/beacon`."""

    id: int
    name: str
    macAddress: str
    batteryLevel: int  # percentage
    lastBatteryLevelUpdate: str
    sleepDelay: int
    isUpdated: bool
    power: str
    mode: str
    model: str
    createdAt: str
    updatedAt: str


class MaintenancePayload(TypedDict, total=False):
    """Shape of one maintenance item from `GET /tracker/{id}/maintenance`."""

    id: int
    trackerId: int
    name: str
    todo: int
    everyMaintenance: int
    lastMaintenance: NotRequired[int | None]
    lastMaintenanceDistance: NotRequired[int | None]
    lastMaintenanceDate: NotRequired[str | None]
    dateUnitType: NotRequired[str | None]  # None | "days" | "years"
    createdAt: str
    updatedAt: str
