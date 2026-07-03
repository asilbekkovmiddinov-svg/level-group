from sqlalchemy import Column, BigInteger
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Wallet(Base):
    __tablename__ = "wallets"

    telegram_id = Column(BigInteger, primary_key=True)

    efc_balance = Column(BigInteger, default=0)

    uzs_balance = Column(BigInteger, default=0)

    locked_efc = Column(BigInteger, default=0)

    locked_uzs = Column(BigInteger, default=0)
