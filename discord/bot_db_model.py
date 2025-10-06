from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey, Text, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker

Base = declarative_base()

class System(Base):
    __tablename__ = 'systems'
    id64 = Column(Integer, primary_key=True)
    name = Column(String)
    x = Column(Float)
    y = Column(Float)
    z = Column(Float)
    controlling_power = Column(String, nullable=True)
    power_state = Column(String, nullable=True)
    powers_acquiring = Column(Text, nullable=True)  # Assuming this is stored as JSON
    distance_from_sol = Column(Float, nullable=True)
    system_state = Column(String, nullable=True)
    population = Column(Integer, nullable=True)
    
    stations = relationship("Station", back_populates="system")
    mineral_signals = relationship("MineralSignal", back_populates="system")

class Station(Base):
    __tablename__ = 'stations'
    system_id64 = Column(Integer, ForeignKey('systems.id64'), primary_key=True)
    station_id = Column(Integer, primary_key=True)
    station_name = Column(String)
    station_type = Column(String, nullable=True)
    landing_pad_size = Column(String, nullable=True)
    distance_to_arrival = Column(Float, nullable=True)
    update_time = Column(String, nullable=True)  # Assuming this is stored as a string
    primary_economy = Column(String, nullable=True)
    body = Column(String, nullable=True)
    
    system = relationship("System", back_populates="stations")
    commodities = relationship("StationCommodity", back_populates="station")

class StationCommodity(Base):
    __tablename__ = 'station_commodities'
    system_id64 = Column(Integer, ForeignKey('stations.system_id64'), primary_key=True)
    station_id = Column(Integer, ForeignKey('stations.station_id'), primary_key=True)
    commodity_name = Column(String, primary_key=True)
    demand = Column(Integer, nullable=True)
    sell_price = Column(Integer, nullable=True)
    
    station = relationship("Station", back_populates="commodities")

class MineralSignal(Base):
    __tablename__ = 'mineral_signals'
    system_id64 = Column(Integer, ForeignKey('systems.id64'), primary_key=True)
    body_name = Column(String, primary_key=True)
    ring_name = Column(String, primary_key=True)
    ring_type = Column(String, nullable=True)
    mineral_type = Column(String, primary_key=True)
    signal_count = Column(Integer, nullable=True)
    reserve_level = Column(String, nullable=True)
    
    system = relationship("System", back_populates="mineral_signals")