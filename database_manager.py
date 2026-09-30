#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库管理器
连接TeslaMate PostgreSQL数据库，执行各种统计查询
"""

import logging
import psycopg2
import psycopg2.extras
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from contextlib import contextmanager
from zoneinfo import ZoneInfo

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class DriveSummary:
    """行程总结数据"""

    total_distance: float  # 总里程 (km)
    total_duration: int  # 总时长 (分钟)
    total_consumption: float  # 总消耗 (kWh)
    avg_efficiency: float  # 平均效率 (Wh/km)
    max_speed: int  # 最高速度 (km/h)
    trip_count: int  # 行程次数
    avg_outside_temp: float  # 平均外部温度


@dataclass
class ChargingSummary:
    """充电总结数据"""

    total_energy_added: float  # 总充电量 (kWh)
    total_cost: float  # 总费用
    charging_sessions: int  # 充电次数
    avg_charging_power: float  # 平均充电功率 (kW)
    total_charging_time: int  # 总充电时长 (分钟)
    home_charging_ratio: float  # 家充比例


@dataclass
class BatteryHealth:
    """电池健康数据"""

    rated_range_km: float  # 额定续航
    estimated_range_km: float  # 预估续航
    degradation_percent: float  # 衰减百分比
    charge_cycles: int  # 充电循环次数
    avg_battery_temp: float  # 平均电池温度


class TeslaMateDatabase:
    """TeslaMate数据库管理器"""

    def __init__(
        self,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        timezone_name: str = "Asia/Shanghai",
    ):
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.local_timezone = ZoneInfo(timezone_name)

        # 测试连接
        self._test_connection()

    def _date_range_to_utc(
        self, start_date: date, end_date: date
    ) -> tuple[datetime, datetime]:
        """把本地自然日范围转换为 TeslaMate 使用的 UTC 边界。"""
        local_start = datetime.combine(start_date, time.min, tzinfo=self.local_timezone)
        local_end = datetime.combine(
            end_date + timedelta(days=1),
            time.min,
            tzinfo=self.local_timezone,
        )
        utc_start = local_start.astimezone(timezone.utc).replace(tzinfo=None)
        utc_end = local_end.astimezone(timezone.utc).replace(tzinfo=None)
        return utc_start, utc_end

    def _test_connection(self):
        """测试数据库连接"""
        try:
            logger.info(
                f"尝试连接数据库: {self.user}@{self.host}:{self.port}/{self.database}"
            )
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT version()")
                    version = cursor.fetchone()[0]
                    logger.info(f"数据库连接成功: {version}")
        except Exception as e:
            logger.error(
                f"数据库连接失败: host={self.host}, port={self.port}, database={self.database}, user={self.user}"
            )
            logger.error(f"详细错误: {e}")
            raise

    @contextmanager
    def _get_connection(self):
        """获取数据库连接上下文管理器"""
        conn = None
        try:
            # 构建连接字符串用于调试
            conn_str = f"host={self.host} port={self.port} dbname={self.database} user={self.user}"
            logger.debug(f"连接字符串: {conn_str}")

            conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
                connect_timeout=10,  # 10秒超时
            )
            yield conn
        except psycopg2.OperationalError as e:
            if conn:
                conn.rollback()
            logger.error(f"数据库连接错误: {e}")
            logger.error(f"错误代码: {e.pgcode if hasattr(e, 'pgcode') else 'N/A'}")
            raise
        except psycopg2.Error as e:
            if conn:
                conn.rollback()
            logger.error(f"数据库错误: {e}")
            logger.error(f"错误代码: {e.pgcode if hasattr(e, 'pgcode') else 'N/A'}")
            raise
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"未知数据库错误: {type(e).__name__}: {e}")
            raise
        finally:
            if conn:
                conn.close()

    def get_cars(self) -> List[Dict[str, Any]]:
        """获取所有车辆信息"""
        query = """
        SELECT 
            id, eid, vid, model, efficiency, 
            display_priority, marketing_name,
            trim_badging, exterior_color, wheel_type,
            inserted_at, updated_at
        FROM cars 
        ORDER BY display_priority, id
        """

        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query)
                return cursor.fetchall()

    def get_drive_summary(
        self, car_id: int, start_date: date, end_date: date
    ) -> Optional[DriveSummary]:
        """获取指定时间段的行程总结"""
        query = """
        SELECT 
            COALESCE(SUM(d.distance), 0) as total_distance,
            COALESCE(SUM(d.duration_min), 0) as total_duration, 
            COALESCE(SUM(d.start_rated_range_km - d.end_rated_range_km), 0) as total_consumption,
            CASE 
                WHEN SUM(d.distance) > 0 THEN COALESCE(SUM(d.start_rated_range_km - d.end_rated_range_km) * 1000 / SUM(d.distance), 0)
                ELSE 0 
            END as avg_efficiency,
            COALESCE(MAX(d.speed_max), 0) as max_speed,
            COUNT(*) as trip_count,
            COALESCE(AVG(d.outside_temp_avg), 0) as avg_outside_temp
        FROM drives d
        WHERE d.car_id = %s 
            AND d.start_date >= %s
            AND d.start_date < %s
            AND d.end_km IS NOT NULL
            AND d.start_rated_range_km IS NOT NULL  
            AND d.end_rated_range_km IS NOT NULL
        """

        utc_start, utc_end = self._date_range_to_utc(start_date, end_date)
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, (car_id, utc_start, utc_end))
                row = cursor.fetchone()

                if row and row["trip_count"] > 0:
                    return DriveSummary(
                        total_distance=float(row["total_distance"] or 0),
                        total_duration=int(row["total_duration"] or 0),
                        total_consumption=float(row["total_consumption"] or 0),
                        avg_efficiency=float(row["avg_efficiency"] or 0),
                        max_speed=int(row["max_speed"] or 0),
                        trip_count=int(row["trip_count"] or 0),
                        avg_outside_temp=float(row["avg_outside_temp"] or 0),
                    )
                return None

    def get_charging_summary(
        self, car_id: int, start_date: date, end_date: date
    ) -> Optional[ChargingSummary]:
        """获取指定时间段的充电总结"""
        query = """
        SELECT 
            COALESCE(SUM(cp.charge_energy_added), 0) as total_energy_added,
            COALESCE(SUM(cp.cost), 0) as total_cost,
            COUNT(cp.id) as charging_sessions,
            COALESCE(AVG(CASE WHEN cp.duration_min > 0 THEN cp.charge_energy_added * 60 / cp.duration_min ELSE 0 END), 0) as avg_charging_power,
            COALESCE(SUM(cp.duration_min), 0) as total_charging_time,
            0.0 as home_charging_ratio
        FROM charging_processes cp
        WHERE cp.car_id = %s 
            AND cp.start_date >= %s
            AND cp.start_date < %s
            AND cp.charge_energy_added > 0
        """

        utc_start, utc_end = self._date_range_to_utc(start_date, end_date)
        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, (car_id, utc_start, utc_end))
                row = cursor.fetchone()

                if row and row["charging_sessions"] > 0:
                    return ChargingSummary(
                        total_energy_added=float(row["total_energy_added"] or 0),
                        total_cost=float(row["total_cost"] or 0),
                        charging_sessions=int(row["charging_sessions"] or 0),
                        avg_charging_power=float(row["avg_charging_power"] or 0),
                        total_charging_time=int(row["total_charging_time"] or 0),
                        home_charging_ratio=float(row["home_charging_ratio"] or 0)
                        * 100,
                    )
                return None

    def get_battery_health(self, car_id: int) -> Optional[BatteryHealth]:
        """获取电池健康状态"""
        # 获取最近的电池数据，从positions表查询（states表没有range字段）
        recent_query = """
        SELECT 
            COALESCE(rated_battery_range_km, est_battery_range_km) as range_km,
            est_battery_range_km,
            battery_level,
            date
        FROM positions 
        WHERE car_id = %s 
            AND COALESCE(rated_battery_range_km, est_battery_range_km) IS NOT NULL
            AND battery_level BETWEEN 95 AND 100
        ORDER BY date DESC 
        LIMIT 10
        """

        # 获取历史电池数据用于计算衰减
        historical_query = """
        SELECT 
            AVG(COALESCE(rated_battery_range_km, est_battery_range_km)) as avg_rated_range,
            date_trunc('month', date) as month
        FROM positions 
        WHERE car_id = %s 
            AND COALESCE(rated_battery_range_km, est_battery_range_km) IS NOT NULL
            AND battery_level BETWEEN 95 AND 100
            AND date >= NOW() - INTERVAL '12 months'
        GROUP BY date_trunc('month', date)
        ORDER BY month
        """

        # 获取充电循环次数估算
        cycles_query = """
        SELECT 
            COUNT(*) as charge_cycles
        FROM charging_processes
        WHERE car_id = %s 
            AND charge_energy_added > 10  -- 只统计实际充电
            AND start_date >= NOW() - INTERVAL '12 months'
        """

        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                # 获取最近数据
                cursor.execute(recent_query, (car_id,))
                recent_data = cursor.fetchall()

                if not recent_data:
                    return None

                # 获取历史数据
                cursor.execute(historical_query, (car_id,))
                historical_data = cursor.fetchall()

                # 获取充电循环次数
                cursor.execute(cycles_query, (car_id,))
                cycles_data = cursor.fetchone()

                # 计算当前续航
                current_rated_range = sum(
                    row["range_km"] for row in recent_data[:5]
                ) / min(5, len(recent_data))
                current_est_range = sum(
                    row["est_battery_range_km"] for row in recent_data[:5]
                ) / min(5, len(recent_data))

                # 计算电池衰减
                degradation_percent = 0.0
                if len(historical_data) >= 2:
                    first_month_range = historical_data[0]["avg_rated_range"]
                    last_month_range = historical_data[-1]["avg_rated_range"]
                    if first_month_range and last_month_range and first_month_range > 0:
                        degradation_percent = (
                            (first_month_range - last_month_range) / first_month_range
                        ) * 100
                        degradation_percent = max(
                            0, degradation_percent
                        )  # 确保不为负数

                return BatteryHealth(
                    rated_range_km=current_rated_range,
                    estimated_range_km=current_est_range,
                    degradation_percent=degradation_percent,
                    charge_cycles=cycles_data["charge_cycles"] if cycles_data else 0,
                    avg_battery_temp=0.0,  # TeslaMate暂不记录电池温度
                )

    def get_recent_trips(self, car_id: int, limit: int = 5) -> List[Dict[str, Any]]:
        """获取最近的行程记录"""
        query = """
        SELECT 
            d.start_date, d.end_date, d.distance, d.duration_min,
            COALESCE(cp.charge_energy_used, 0) as consumption_kwh,
            CASE 
                WHEN d.distance > 0 THEN COALESCE(cp.charge_energy_used * 100 / d.distance, 0)
                ELSE 0 
            END as consumption_kwh_100km,
            -- 优先显示收藏点名称，如果没有则显示地址
            COALESCE(start_geo.name, sa.display_name) as start_address,
            COALESCE(end_geo.name, ea.display_name) as end_address,
            sa.display_name as start_full_address,
            ea.display_name as end_full_address,
            sa.latitude as start_latitude,
            sa.longitude as start_longitude,
            ea.latitude as end_latitude,
            ea.longitude as end_longitude,
            d.speed_max,
            d.outside_temp_avg,
            -- 获取行程开始和结束时的电池电量
            start_pos.battery_level as start_battery_level,
            end_pos.battery_level as end_battery_level
        FROM drives d
        LEFT JOIN addresses sa ON sa.id = d.start_address_id
        LEFT JOIN addresses ea ON ea.id = d.end_address_id
        LEFT JOIN geofences start_geo ON start_geo.id = d.start_geofence_id
        LEFT JOIN geofences end_geo ON end_geo.id = d.end_geofence_id
        LEFT JOIN charging_processes cp ON cp.car_id = d.car_id 
            AND cp.start_date <= d.end_date 
            AND cp.end_date >= d.start_date
        LEFT JOIN positions start_pos ON start_pos.id = d.start_position_id
        LEFT JOIN positions end_pos ON end_pos.id = d.end_position_id
        WHERE d.car_id = %s 
            AND d.end_km IS NOT NULL
            AND d.distance > 0
        ORDER BY d.start_date DESC 
        LIMIT %s
        """

        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, (car_id, limit))
                return cursor.fetchall()

    def get_charging_in_progress(self, car_id: int) -> Optional[Dict[str, Any]]:
        """获取正在进行的充电过程"""
        query = """
        SELECT 
            cp.id, cp.start_date, cp.start_battery_level,
            cp.charge_energy_added, cp.duration_min,
            a.display_name as location_name,
            s.battery_level as current_battery_level
        FROM charging_processes cp
        LEFT JOIN addresses a ON a.id = cp.address_id  
        LEFT JOIN LATERAL (
            SELECT battery_level
            FROM positions 
            WHERE car_id = cp.car_id 
            ORDER BY date DESC 
            LIMIT 1
        ) s ON true
        WHERE cp.car_id = %s 
            AND cp.end_date IS NULL
        ORDER BY cp.start_date DESC
        LIMIT 1
        """

        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, (car_id,))
                return cursor.fetchone()

    def get_latest_completed_charging(self, car_id: int) -> Optional[Dict[str, Any]]:
        """获取最新完成的充电信息（包含收藏点和坐标）"""
        query = """
        SELECT 
            cp.id, cp.start_date, cp.end_date,
            cp.start_battery_level, cp.end_battery_level,
            cp.charge_energy_added, cp.duration_min,
            cp.cost, 
            -- 优先显示收藏点名称，如果没有则显示地址
            COALESCE(g.name, a.display_name) as location_name,
            a.display_name as full_address,
            a.latitude, a.longitude
        FROM charging_processes cp
        LEFT JOIN addresses a ON a.id = cp.address_id
        LEFT JOIN geofences g ON g.id = cp.geofence_id
        WHERE cp.car_id = %s 
            AND cp.end_date IS NOT NULL
        ORDER BY cp.end_date DESC
        LIMIT 1
        """

        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, (car_id,))
                return cursor.fetchone()

    def get_software_update_info(self, car_id: int) -> Optional[Dict[str, Any]]:
        """获取软件更新信息"""
        query = """
        SELECT 
            NULL::text as current_version,
            version as update_version,
            date_trunc('day', start_date) as check_date,
            CASE WHEN end_date IS NULL THEN true ELSE false END as update_available
        FROM updates 
        WHERE car_id = %s 
        ORDER BY start_date DESC 
        LIMIT 1
        """

        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, (car_id,))
                return cursor.fetchone()

    def get_daily_stats(self, car_id: int, target_date: date) -> Dict[str, Any]:
        """获取指定日期的统计数据"""
        drive_summary = self.get_drive_summary(car_id, target_date, target_date)
        charging_summary = self.get_charging_summary(car_id, target_date, target_date)

        return {
            "date": target_date,
            "driving": drive_summary,
            "charging": charging_summary,
        }

    def get_weekly_stats(self, car_id: int, week_start: date) -> Dict[str, Any]:
        """获取周统计数据"""
        week_end = week_start + timedelta(days=6)
        drive_summary = self.get_drive_summary(car_id, week_start, week_end)
        charging_summary = self.get_charging_summary(car_id, week_start, week_end)

        return {
            "week_start": week_start,
            "week_end": week_end,
            "driving": drive_summary,
            "charging": charging_summary,
        }

    def get_monthly_stats(self, car_id: int, year: int, month: int) -> Dict[str, Any]:
        """获取月统计数据"""
        month_start = date(year, month, 1)
        if month == 12:
            month_end = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            month_end = date(year, month + 1, 1) - timedelta(days=1)

        drive_summary = self.get_drive_summary(car_id, month_start, month_end)
        charging_summary = self.get_charging_summary(car_id, month_start, month_end)
        battery_health = self.get_battery_health(car_id)

        return {
            "year": year,
            "month": month,
            "month_start": month_start,
            "month_end": month_end,
            "driving": drive_summary,
            "charging": charging_summary,
            "battery_health": battery_health,
        }
