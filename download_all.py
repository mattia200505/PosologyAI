import requests
import json
import os
import time


BASE_URL = "https://uxn2ycvimg.us-east-2.awsapprunner.com/"

LIMIT = 1000
DATA_DIR = "data"


DATASETS = [

    "structures",
    "targets",
    "atc",
    "struct2atc",
    "drug_class",
    "td2tc",
    "omop_relationship",
    "struct2obprod",
    "faers",
    "faers_female",
    "faers_male"

]


os.makedirs(DATA_DIR, exist_ok=True)


def download_dataset(name):

    print("\nSTART", name)

    all_data = []
    skip = 0

    while True:

        url = (
            f"{BASE_URL}/{name}"
            f"?skip={skip}&limit={LIMIT}"
        )

        for attempt in range(5):

            try:

                r = requests.get(
                    url,
                    timeout=60
                )

                if r.status_code == 200:

                    batch = r.json()

                    break

                else:

                    print(
                        "HTTP",
                        r.status_code
                    )

            except Exception as e:

                print(
                    "ERROR",
                    e
                )

            time.sleep(5)

        else:

            print(
                "STOP",
                name
            )

            break



        if not batch:

            break



        all_data.extend(batch)


        print(
            name,
            len(all_data),
            "records"
        )


        skip += LIMIT


        time.sleep(0.2)



    path = (
        f"{DATA_DIR}/{name}.json"
    )


    with open(
        path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            all_data,
            f,
            ensure_ascii=False,
            indent=2
        )



    print(
        "SAVED",
        path,
        len(all_data)
    )




for ds in DATASETS:

    download_dataset(ds)



print("\nDONE ALL DOWNLOAD")