"""Paginasi server-side untuk tabel halaman web REPTIL.

Semua halaman daftar memakai pola yang sama:

1. Ambil daftar lengkap hasil filter dari service (mis. ``list_partners``).
2. Bungkus dengan :func:`halaman` yang membaca ``?page`` & ``?per_page`` dari
   query string dan memotong daftar sesuai halaman aktif.
3. Kirim ``h.items`` sebagai daftar baris dan ``h`` untuk widget navigasi
   (lihat makro ``_pager.html``).

Filter aktif ikut tersimpan di dalam tautan paginasi sehingga berpindah
halaman tidak menghilangkan keyword/status yang sedang dipilih.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil
from urllib.parse import urlencode

from fastapi import Request

PER_PAGE_DEFAULT = 20
PER_PAGE_PILIHAN: tuple[int, ...] = (10, 20, 50, 100)
_PARAM_DILEWATI = ("page", "per_page")


@dataclass(slots=True)
class Halaman:
    """Hasil pemotongan daftar + metadata untuk widget paginasi."""

    items: list
    page: int
    per_page: int
    total: int
    params: list[tuple[str, str]] = field(default_factory=list)
    pilihan: tuple[int, ...] = PER_PAGE_PILIHAN

    @property
    def total_halaman(self) -> int:
        return max(1, ceil(self.total / self.per_page))

    @property
    def mulai(self) -> int:
        """Nomor urut baris pertama pada halaman ini (1-based, 0 bila kosong)."""
        return 0 if not self.total else (self.page - 1) * self.per_page + 1

    @property
    def sampai(self) -> int:
        return min(self.page * self.per_page, self.total)

    @property
    def punya_sebelum(self) -> bool:
        return self.page > 1

    @property
    def punya_berikut(self) -> bool:
        return self.page < self.total_halaman

    def url(self, page: int, per_page: int | None = None) -> str:
        """Query string relatif untuk halaman tertentu (mempertahankan filter)."""
        pasangan = [*self.params, ("page", str(page)), ("per_page", str(per_page or self.per_page))]
        return f"?{urlencode(pasangan)}"

    def nomor(self) -> list[int | None]:
        """Nomor halaman yang ditampilkan; ``None`` berarti elipsis (…)."""
        total = self.total_halaman
        if total <= 7:
            return list(range(1, total + 1))
        tampil = {1, total, self.page - 1, self.page, self.page + 1}
        if self.page <= 3:
            tampil |= {2, 3, 4}
        if self.page >= total - 2:
            tampil |= {total - 1, total - 2, total - 3}
        hasil: list[int | None] = []
        sebelumnya = 0
        for nomor in sorted(n for n in tampil if 1 <= n <= total):
            if sebelumnya and nomor - sebelumnya > 1:
                hasil.append(None)
            hasil.append(nomor)
            sebelumnya = nomor
        return hasil


def _ke_int(nilai: object, default: int) -> int:
    try:
        return int(nilai)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def paginate(
    items: list,
    *,
    page: int = 1,
    per_page: int = PER_PAGE_DEFAULT,
    params: list[tuple[str, str]] | None = None,
) -> Halaman:
    """Potong ``items`` menjadi satu halaman; aman terhadap nilai tak valid."""
    if per_page not in PER_PAGE_PILIHAN:
        per_page = PER_PAGE_DEFAULT
    page = max(1, page)
    total = len(items)
    total_halaman = max(1, ceil(total / per_page))
    page = min(page, total_halaman)
    mulai = (page - 1) * per_page
    return Halaman(
        items=list(items[mulai : mulai + per_page]),
        page=page,
        per_page=per_page,
        total=total,
        params=list(params or []),
    )


def halaman(request: Request, items: list, *, abaikan: tuple[str, ...] = ()) -> Halaman:
    """Bangun :class:`Halaman` dari query string request.

    ``abaikan`` dipakai halaman yang punya parameter non-filter (mis. ``edit``
    pada halaman armada/ekspedisi) agar tidak menempel di tautan paginasi.
    """
    qp = request.query_params
    page = _ke_int(qp.get("page"), 1)
    per_page = _ke_int(qp.get("per_page"), PER_PAGE_DEFAULT)
    lewati = {*_PARAM_DILEWATI, *abaikan}
    params = [(k, v) for k, v in qp.multi_items() if k not in lewati and v != ""]
    return paginate(items, page=page, per_page=per_page, params=params)


__all__ = [
    "PER_PAGE_DEFAULT",
    "PER_PAGE_PILIHAN",
    "Halaman",
    "halaman",
    "paginate",
]
