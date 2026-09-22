from datetime import datetime

from worker import report_schedule
from worker.reports.formatter import format_morning_message


def test_bom_dia_as_seis_em_ponto():
    assert (report_schedule.MORNING_HOUR, report_schedule.MORNING_MINUTE) == (6, 0)
    assert report_schedule.is_morning_time(datetime(2026, 9, 23, 6, 0))
    assert report_schedule.is_morning_time(datetime(2026, 9, 23, 6, 40))
    assert not report_schedule.is_morning_time(datetime(2026, 9, 23, 5, 59))
    assert not report_schedule.is_morning_time(datetime(2026, 9, 23, 7, 0))


def test_ciclos_de_duas_em_duas_horas_das_0630_as_2030():
    assert report_schedule.cycle_labels() == (
        "06:30", "08:30", "10:30", "12:30",
        "14:30", "16:30", "18:30", "20:30",
    )


def test_ciclo_so_dispara_a_partir_do_minuto_configurado():
    assert not report_schedule.is_cycle_time(datetime(2026, 9, 23, 6, 29))
    assert report_schedule.is_cycle_time(datetime(2026, 9, 23, 6, 30))
    assert report_schedule.is_cycle_time(datetime(2026, 9, 23, 6, 59))


def test_ciclo_nao_dispara_em_hora_fora_da_agenda():
    assert not report_schedule.is_cycle_time(datetime(2026, 9, 23, 7, 30))
    assert not report_schedule.is_cycle_time(datetime(2026, 9, 23, 22, 30))
    assert not report_schedule.is_cycle_time(datetime(2026, 9, 23, 5, 30))


def test_ultimo_ciclo_do_dia_e_2030():
    assert report_schedule.is_cycle_time(datetime(2026, 9, 23, 20, 30))
    assert not report_schedule.is_cycle_time(datetime(2026, 9, 23, 20, 29))


def test_bom_dia_anuncia_o_cronograma_real():
    """A mensagem nao pode prometer um horario diferente do que o scheduler
    executa: ela e lida pelo time todo dia."""
    mensagem = format_morning_message()

    for label in report_schedule.cycle_labels():
        assert label in mensagem
    assert "06:10" not in mensagem
