from app.core.database import engine, Base
from app.models.p2p import P2POrder, P2PTrade


def reset_p2p_tables():
    P2PTrade.__table__.drop(bind=engine, checkfirst=True)
    P2POrder.__table__.drop(bind=engine, checkfirst=True)

    P2POrder.__table__.create(bind=engine, checkfirst=True)
    P2PTrade.__table__.create(bind=engine, checkfirst=True)

    print("P2P tables reset qilindi")


if __name__ == "__main__":
    reset_p2p_tables()
