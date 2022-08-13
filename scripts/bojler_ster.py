# porgram sterujacy bojlerem i pompa obiegową na podstawie trayfy, pracy pompy ciepła orac mocy z paneli fotowoltaicznych
from datetime import datetime, timedelta
from statistics import mean
import dzarwis_global_vars as dgv
from time import sleep
from influxdb import InfluxDBClient

def read_return_power(db_client ):
    #funkcja odczytuje średnia moc zwracana do sieci w ciagu ostanich 5 minut
    mean_power = 0
    query = f'SELECT "P1" FROM "licznik" WHERE time>= now() -5m AND time <= now()'
    energia = list(db_client.query(query).get_points())
    for e in energia:
        #print (e['P1'])
        mean_power +=e['P1']
    mean_power = mean_power / len(energia)
    #print(mean_power)
    return(mean_power)

def main():
    power_db = InfluxDBClient(dgv.influx_ip , dgv.influx_port, dgv.influx_user, dgv.influx_password,dgv.influx_energia_db_name)
    while True:
        return_power =read_return_power(power_db)
        now = datetime.now()
        ntd_start=(now.replace(hour=dgv.NT_day_start,minute =0, second=0))
        ntd_stop=(now.replace(hour=dgv.NT_day_stop,minute =0, second=0))
        miesznie_poranne = now.replace(hour = dgv.mix_hour, minute =0, second=0)
        stop_miesznie_poranne = miesznie_poranne + timedelta(minutes = dgv.mix_time)
        if now > miesznie_poranne and now < stop_miesznie_poranne:
            print(f'start miesznie{now}')
        if now > ntd_start and now < ntd_stop:
            print (f'włącz grznie niska taryfa dzienna: {now}')
        else:
            if return_power < -2000:
                print(f'załącz grznie, moc oddawana:{return_power}')
            else:
                print(f'wylącz grznie, moc oddawana:{return_power}')
        sleep(60)

if __name__ == "__main__":
    main()