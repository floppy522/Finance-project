from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from moneyflow.models import TransactionType


@dataclass(frozen=True, slots=True)
class CategoryCatalogEntry:
    code: str
    transaction_type: TransactionType
    name_ru: str
    sort_order: int


@dataclass(frozen=True, slots=True)
class LocalCategoryRule:
    phrase: str
    category_code: str
    transaction_type: TransactionType
    priority: int = 100


CATEGORY_CATALOG: Final[tuple[CategoryCatalogEntry, ...]] = (
    CategoryCatalogEntry("expense.groceries", TransactionType.EXPENSE, "Продукты", 1),
    CategoryCatalogEntry("expense.cafes", TransactionType.EXPENSE, "Кафе и рестораны", 2),
    CategoryCatalogEntry("expense.transport", TransactionType.EXPENSE, "Транспорт", 3),
    CategoryCatalogEntry("expense.housing", TransactionType.EXPENSE, "Жильё", 4),
    CategoryCatalogEntry("expense.health", TransactionType.EXPENSE, "Здоровье", 5),
    CategoryCatalogEntry("expense.shopping", TransactionType.EXPENSE, "Покупки", 6),
    CategoryCatalogEntry("expense.entertainment", TransactionType.EXPENSE, "Развлечения", 7),
    CategoryCatalogEntry("expense.subscriptions", TransactionType.EXPENSE, "Подписки", 8),
    CategoryCatalogEntry("expense.travel", TransactionType.EXPENSE, "Путешествия", 9),
    CategoryCatalogEntry("expense.education", TransactionType.EXPENSE, "Образование", 10),
    CategoryCatalogEntry("expense.gifts", TransactionType.EXPENSE, "Подарки", 11),
    CategoryCatalogEntry("expense.other", TransactionType.EXPENSE, "Прочее", 12),
    CategoryCatalogEntry("income.salary", TransactionType.INCOME, "Зарплата", 1),
    CategoryCatalogEntry("income.investments", TransactionType.INCOME, "Инвестиционный доход", 2),
    CategoryCatalogEntry("income.refunds", TransactionType.INCOME, "Возвраты", 3),
    CategoryCatalogEntry("income.gifts", TransactionType.INCOME, "Подарки", 4),
    CategoryCatalogEntry("income.other", TransactionType.INCOME, "Прочее", 5),
)

CATEGORY_BY_CODE = MappingProxyType({entry.code: entry for entry in CATEGORY_CATALOG})

LOCAL_CATEGORY_RULES: Final[tuple[LocalCategoryRule, ...]] = (
    LocalCategoryRule("кофе", "expense.cafes", TransactionType.EXPENSE),
    LocalCategoryRule("кафе", "expense.cafes", TransactionType.EXPENSE),
    LocalCategoryRule("ресторан", "expense.cafes", TransactionType.EXPENSE),
    LocalCategoryRule("вкусвилл", "expense.groceries", TransactionType.EXPENSE),
    LocalCategoryRule("пятерочка", "expense.groceries", TransactionType.EXPENSE),
    LocalCategoryRule("перекресток", "expense.groceries", TransactionType.EXPENSE),
    LocalCategoryRule("магнит", "expense.groceries", TransactionType.EXPENSE),
    LocalCategoryRule("продукты", "expense.groceries", TransactionType.EXPENSE),
    LocalCategoryRule("такси", "expense.transport", TransactionType.EXPENSE),
    LocalCategoryRule("метро", "expense.transport", TransactionType.EXPENSE),
    LocalCategoryRule("автобус", "expense.transport", TransactionType.EXPENSE),
    LocalCategoryRule("бензин", "expense.transport", TransactionType.EXPENSE),
    LocalCategoryRule("аренда", "expense.housing", TransactionType.EXPENSE),
    LocalCategoryRule("ипотека", "expense.housing", TransactionType.EXPENSE),
    LocalCategoryRule("аптека", "expense.health", TransactionType.EXPENSE),
    LocalCategoryRule("врач", "expense.health", TransactionType.EXPENSE),
    LocalCategoryRule("подписка", "expense.subscriptions", TransactionType.EXPENSE),
    LocalCategoryRule("отель", "expense.travel", TransactionType.EXPENSE),
    LocalCategoryRule("авиабилет", "expense.travel", TransactionType.EXPENSE),
    LocalCategoryRule("курс", "expense.education", TransactionType.EXPENSE),
    LocalCategoryRule("обучение", "expense.education", TransactionType.EXPENSE),
    LocalCategoryRule("зарплата", "income.salary", TransactionType.INCOME),
    LocalCategoryRule("дивиденды", "income.investments", TransactionType.INCOME),
    LocalCategoryRule("проценты по вкладу", "income.investments", TransactionType.INCOME),
    LocalCategoryRule("возврат", "income.refunds", TransactionType.INCOME),
)


def category_matches_type(category_code: str, transaction_type: TransactionType) -> bool:
    category = CATEGORY_BY_CODE.get(category_code)
    return category is not None and category.transaction_type is transaction_type
