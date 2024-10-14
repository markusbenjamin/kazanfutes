from utils.project import *

def get_sheet_data(spreadsheet_id, sheet = None):
    """
    Uses the Google Sheets API to download the contents of either the first sheet of a spreadsheet (if sheet == None), or from the sheet specified.
    """
    try:
        credentials = Credentials.from_service_account_file(
            os.path.join(get_project_root(),'config','secrets_and_env','sheets-access-key.json'), 
            scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
            )
        service = build('sheets', 'v4', credentials=credentials)
        spreadsheet_metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    except:
        raise ModuleException("failed to set up Google Sheets API")
    
    try:
        if sheet:
            sheet_names = []
            for sheet_data in spreadsheet_metadata['sheets']:
                sheet_names.append(sheet_data['properties']['title'])
            if sheet not in sheet_names:
                raise ModuleException(f"requested sheet '{sheet}' not in spreadsheet '{spreadsheet_metadata['properties']['title']}'")
        else:
            sheet = spreadsheet_metadata['sheets'][0]['properties']['title']
        
        range_to_get = sheet +'!A1:Z10000'

        sheet = service.spreadsheets()
        result = sheet.values().get(spreadsheetId=spreadsheet_id, range=range_to_get).execute()
        values = result.get('values', [])

        return values
    except ModuleException as e:
        raise
    except:
        raise ModuleException(f"failed to download sheet '{sheet}' from spreadsheet '{spreadsheet_metadata['properties']['title']}'")

heating_control_config = load_json_to_dict('config/heating_control_config.json')
rooms_info = get_rooms_info()

new_call = get_sheet_data(heating_control_config['weekly_cycle_id'],rooms_info['1']['name'])
old_call = download_csv_to_2D_array(f"{heating_control_config['weekly_cycle_url']}&gid={rooms_info['1']['schedule_gid']}")

print(new_call)
print(old_call)