import sys

# GDELT 2.0 Event Database Column positions
# Column 58 should be ActionGeo_Long (Longitude)
# Column 56 should be ActionGeo_Type (Location Type ID)
# Reference: http://data.gdeltproject.org/documentation/GDELT-Event_Codebook-V2.0.pdf

print("GDELT 2.0 ActionGeo fields:")
print("Column 54: ActionGeo_Type (Location type)")  
print("Column 55: ActionGeo_FullName")
print("Column 56: ActionGeo_CountryCode")
print("Column 57: ActionGeo_ADM1Code") 
print("Column 58: ActionGeo_ADM2Code")  # THIS IS NOT LONGITUDE!
print("Column 59: ActionGeo_Lat")
print("Column 60: ActionGeo_Long")
print("Column 61: ActionGeo_FeatureID")  # This could be the location ID!

print("\n⚠️  WARNING: Column 58 is ADM2 Code, NOT longitude!")
print("⚠️  Longitude should be column 60, not 58!")
